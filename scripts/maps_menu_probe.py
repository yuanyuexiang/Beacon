"""测试期 Maps 菜单探针；不写正式线索库、不调用模型。
运行：uv run --no-project --with playwright==1.63.0 --with 'httpx[socks]' scripts/maps_menu_probe.py --help
"""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlencode, urlparse

import httpx
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import sync_playwright

MENU = re.compile(r"^(Menu|菜单|菜單)$", re.IGNORECASE)
PHOTO = re.compile(
    r"^(Photo \d+ of \d+|第\s*\d+\s*张照片，共\s*\d+\s*张)$", re.IGNORECASE
)


def maps_url(name, address, place_id):
    values = {"api": "1", "query": f"{name} {address}".strip()}
    if place_id:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", place_id):
            raise ValueError("无效 Place ID")
        values["query_place_id"] = place_id
    return "https://www.google.com/maps/search/?" + urlencode(values)


def photo_url(viewer):
    u = urlparse(viewer)
    if (
        u.scheme != "https"
        or u.hostname != "www.google.com"
        or not u.path.startswith("/maps/")
    ):
        raise ValueError("必须使用 www.google.com/maps 的图片查看器 URL")
    decoded = unquote(viewer)
    hit = re.search(r"!6s(https://[^!]+)!7i(\d+)!8i(\d+)", decoded)
    if not hit:
        return None
    source, width, height = hit.groups()
    parsed = urlparse(source)
    if parsed.hostname != "lh3.googleusercontent.com" or parsed.scheme != "https":
        raise ValueError("未知图片来源")
    width, height = min(int(width), 4096), min(int(height), 4096)
    source = re.sub(r"=w\d+-h\d+[^?]*$", f"=w{width}-h{height}-k-no", source)
    return source


def _download_once(source, out, proxy):
    # 单张限 15 MB；不跟随到其他域名，不使用 Google API Key。
    with (
        httpx.Client(
            proxy=proxy or None, trust_env=False, timeout=20, follow_redirects=False
        ) as client,
        client.stream("GET", source) as response,
    ):
        response.raise_for_status()
        mime = response.headers.get("content-type", "").split(";")[0]
        suffix = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(mime)
        if not suffix:
            raise ValueError("未返回受支持的图片")
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > 15 * 1024 * 1024:
                raise ValueError("图片超出大小限制")
    digest = hashlib.sha256(body).hexdigest()
    path = out / (digest[:16] + suffix)
    path.write_bytes(body)
    return {
        "file": path.name,
        "sha256": digest,
        "bytes": len(body),
        "source_url": source,
    }


def download(source, out, proxy):
    for attempt in range(2):
        try:
            return _download_once(source, out, proxy)
        except (httpx.TransportError, httpx.TimeoutException):
            if attempt:
                raise
    raise RuntimeError("unreachable")


def run(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "images": [],
        "name": args.name,
        "place_id": args.place_id,
    }
    url = args.viewer_url or maps_url(args.name, args.address, args.place_id)
    report["maps_url"] = url
    try:
        if args.viewer_url:
            # 人工已从菜单区打开的查看器，作为测试输入；不声称完成自动定位。
            source = photo_url(url)
            if not source:
                raise ValueError("查看器 URL 没有图片资源")
            report["images"].append(
                download(source, out, args.proxy.replace("socks5://", "socks5h://"))
            )
            report["status"] = "downloaded_from_confirmed_viewer"
        else:
            with sync_playwright() as p:
                options = {
                    "channel": "chrome",
                    "headless": args.headless,
                    "viewport": {"width": 1440, "height": 1000},
                    "locale": "en-GB",
                }
                if args.proxy:
                    options["proxy"] = {
                        "server": args.proxy.replace("socks5h://", "socks5://")
                    }
                profile = Path(args.profile).resolve()
                profile.mkdir(parents=True, exist_ok=True, mode=0o700)
                profile.chmod(0o700)
                context = p.chromium.launch_persistent_context(str(profile), **options)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    if args.setup_login:
                        print("请在专用测试浏览器手动登录 Google；完成后在终端按回车。")
                        input()
                        report["status"] = "profile_prepared"
                        return report
                    page.get_by_role("heading", level=1).first.wait_for(timeout=20000)
                    # 验证具体门店；没有确认 ID 的搜索结果不自动采用。
                    actual = page.get_by_role("heading", level=1).first.inner_text()
                    report["observed_name"] = actual
                    if actual.casefold().strip() != args.name.casefold().strip():
                        report["status"] = "place_needs_review"
                        return report
                    text = page.locator("body").inner_text()
                    if "limited view" in text or "有限视图" in text:
                        report["status"] = "limited_view_login_required"
                        return report
                    if (
                        "/sorry/" in page.url
                        or page.locator('iframe[src*="recaptcha"]').count()
                    ):
                        report["status"] = "captcha_requires_manual"
                        return report
                    tab = page.get_by_role("tab", name=MENU)
                    if not tab.count():
                        report["status"] = "menu_tab_unavailable"
                        return report
                    tab.first.click()
                    heading = page.get_by_role("heading", name=MENU).first
                    heading.wait_for(timeout=15000)
                    # 用语义标题的最近容器限定菜单区，避免抓取“亮点”照片。
                    section = heading.locator("xpath=..").locator("xpath=..")
                    cards = section.get_by_role("button", name=PHOTO)
                    total = cards.count()
                    report["menu_thumbnails"] = total
                    for index in range(min(total, args.max_photos)):
                        cards.nth(index).click()
                        page.wait_for_function(
                            "location.href.includes('!6shttps:')", timeout=15000
                        )
                        viewer = page.url
                        source = photo_url(viewer)
                        if source:
                            image = download(
                                source,
                                out,
                                args.proxy.replace("socks5://", "socks5h://"),
                            )
                            image["viewer_url"] = viewer
                            if image["sha256"] not in {
                                x["sha256"] for x in report["images"]
                            }:
                                report["images"].append(image)
                        if index + 1 < min(total, args.max_photos):
                            page.go_back(wait_until="domcontentloaded")
                            heading.wait_for(timeout=15000)
                    report["status"] = (
                        "downloaded" if report["images"] else "menu_images_unavailable"
                    )
                finally:
                    context.close()
    except BrowserTimeout:
        report["status"] = "page_timeout"
    except (httpx.HTTPError, ValueError, BrowserError, EOFError) as e:
        report["status"] = "failed"
        report["error"] = str(e)[:300]
    finally:
        (out / "result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--address", default="")
    parser.add_argument("--place-id")
    parser.add_argument("--viewer-url", help="人工从菜单区打开的照片查看器 URL")
    parser.add_argument("--proxy", default="socks5://127.0.0.1:7890")
    parser.add_argument("--profile", default="data/browser-profiles/maps-menu-test")
    parser.add_argument("--out", default="data/records/maps-menu-test")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headed", dest="headless", action="store_false", default=False)
    mode.add_argument("--headless", action="store_true")
    parser.add_argument("--setup-login", action="store_true")
    parser.add_argument("--max-photos", type=int, choices=range(1, 21), default=10)
    args = parser.parse_args()
    if args.setup_login:
        args.headless = False
    result = run(args)
    print(
        json.dumps(
            {"status": result["status"], "images": len(result["images"])},
            ensure_ascii=False,
        )
    )
