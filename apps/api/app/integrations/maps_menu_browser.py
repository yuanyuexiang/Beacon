"""有界 Maps 菜单浏览器适配器；Playwright 只在专用执行器进程导入。"""

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlencode, urlsplit

import httpx

MENU = re.compile(r"^(Menu|菜单|菜單)$", re.I)
PHOTO = re.compile(r"^(Photo \d+ of \d+|第\s*\d+\s*张照片，共\s*\d+\s*张)$", re.I)
MAX_BYTES = 15 * 1024 * 1024
MESSAGES = {
    "downloaded": "菜单图片已获取；日期和内容仍需核对",
    "limited_view": "Google Maps 返回有限视图；当前会话无法获取菜单，不一定需要登录",
    "consent_required": "Google Cookie 页面未能完成处理，请检查浏览器执行器",
    "captcha": "Google 要求人工验证，请在专用浏览器处理后重试",
    "place_mismatch": "页面名称或地址与目标门店不一致，未导入图片",
    "menu_unavailable": "当前页面未找到菜单页签，可改用官网菜单",
    "images_unavailable": "菜单页签中未找到可下载的菜单图片",
    "timeout": "Google Maps 页面加载超时，请重试",
    "failed": "浏览器或图片下载失败，请检查执行器和网络后重试",
}


def maps_url(name: str, address: str, place_id: str | None) -> str:
    query = {"api": "1", "query": f"{name} {address}".strip()}
    if place_id:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", place_id):
            raise ValueError("无效 Place ID")
        query["query_place_id"] = place_id
    return "https://www.google.com/maps/search/?" + urlencode(query)


def photo_url(viewer: str) -> str | None:
    parsed = urlsplit(viewer)
    if parsed.scheme != "https" or parsed.hostname != "www.google.com" or not parsed.path.startswith("/maps/"):
        raise ValueError("图片必须来自 Google Maps 查看器")
    hit = re.search(r"!6s(https://[^!]+)!7i(\d+)!8i(\d+)", unquote(viewer))
    if not hit:
        return None
    source, width, height = hit.groups()
    parsed = urlsplit(source)
    if parsed.scheme != "https" or parsed.hostname != "lh3.googleusercontent.com" or parsed.username:
        raise ValueError("未知图片来源")
    return re.sub(r"=w\d+-h\d+[^?]*$", f"=w{min(int(width), 4096)}-h{min(int(height), 4096)}-k-no", source)


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def address_norm(value: str) -> str:
    equivalents = {"pl": "place", "rd": "road", "st": "street", "ave": "avenue", "ln": "lane", "dr": "drive"}
    value = re.sub(r"\b(pl|rd|st|ave|ln|dr)\b\.?", lambda hit: equivalents[hit[1]], value.lower())
    return norm(value)


def identity_check(name: str, address: str, postcode: str, actual_name: str, actual_address: str) -> dict:
    # 注册名称可带 THE / AND DELI，但不把不同品牌仅凭同地址合并。
    ignored = {"the", "and", "deli", "restaurant", "bar", "ltd", "limited"}

    def words(value: str) -> set[str]:
        value = re.sub(r"\b(?:community interest company|c\.?i\.?c\.?|ltd|limited)\.?\s*$", "", value, flags=re.I)
        return set(re.findall(r"[a-z0-9]+", value.lower())) - ignored

    expected, actual = words(name), words(actual_name)
    name_ok = norm(name) == norm(actual_name) or bool(expected and actual and expected == actual)
    parts = [part.strip() for part in address.split(",") if part.strip()]
    # FSA 地址可能先列出 Shop / Unit 等场所类型，不能把 Shop 当作街道。
    while len(parts) > 1 and re.fullmatch(r"(?:shop|unit|premises|ground floor|first floor)", parts[0], re.I):
        parts.pop(0)
    street = address_norm(parts[0] if parts else "")
    location = address_norm(actual_address)
    street_ok = bool(street and re.search(r"(?<![0-9])" + re.escape(street), location))
    postcode_ok = bool(norm(postcode) and norm(postcode) in location)
    return {"name_matches": name_ok, "street_matches": street_ok, "postcode_matches": postcode_ok}


def identity_matches(name: str, address: str, postcode: str, actual_name: str, actual_address: str) -> bool:
    return all(identity_check(name, address, postcode, actual_name, actual_address).values())


def download(source: str, out: Path, proxy: str) -> dict:
    for attempt in range(2):
        try:
            with (
                httpx.Client(proxy=proxy or None, trust_env=False, timeout=20, follow_redirects=False) as client,
                client.stream("GET", source) as response,
            ):
                response.raise_for_status()
                mime = response.headers.get("content-type", "").split(";")[0]
                suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime)
                if not suffix:
                    raise ValueError("不支持的图片格式")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("图片超过 15 MB")
            sha = hashlib.sha256(data).hexdigest()
            path = out / (sha + suffix)
            path.write_bytes(data)
            return {"file": str(path), "source_url": source, "sha256": sha, "content_type": mime}
        except httpx.TransportError:
            if attempt:
                raise
    raise RuntimeError("下载失败")


def dismiss_consent(page) -> bool:
    """只处理 Google 的已知同意页；不把中间页面当成门店。"""
    if urlsplit(page.url).hostname != "consent.google.com":
        return True
    reject = page.get_by_role("button", name=re.compile(r"^(Reject all|全部拒绝|拒绝全部)$", re.I))
    if not reject.count():
        return False
    reject.first.click()
    page.wait_for_url(lambda url: urlsplit(url).hostname != "consent.google.com", timeout=30000)
    page.wait_for_load_state("domcontentloaded")
    return True


def capture(
    job: dict,
    profile: Path,
    out: Path,
    proxy: str,
    headless: bool = False,
    progress: Callable[[str], None] = lambda _: None,
) -> dict:
    from playwright.sync_api import Error as BrowserError
    from playwright.sync_api import TimeoutError as BrowserTimeout
    from playwright.sync_api import sync_playwright

    report: dict = {"status": "failed", "images": [], "maps_url": job["maps_url"]}
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(profile),
                channel="chrome",
                headless=headless,
                locale="en-GB",
                viewport={"width": 1440, "height": 1000},
                proxy={"server": proxy.replace("socks5h://", "socks5://")} if proxy else None,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                progress("打开 Google Maps 门店")
                page.goto(job["maps_url"], wait_until="domcontentloaded", timeout=45000)
                if not dismiss_consent(page):
                    report["status"] = "consent_required"
                    return report
                if "/sorry/" in page.url or page.locator('iframe[src*="recaptcha"]').count():
                    report["status"] = "captcha"
                    return report
                page.get_by_role("heading", level=1).first.wait_for(timeout=20000)
                name = page.get_by_role("heading", level=1).first.inner_text()
                body = page.locator("body").inner_text()
                if re.search(r"limited view|有限视图", body, re.I):
                    report["status"] = "limited_view"
                    return report
                address_button = page.locator('button[data-item-id="address"]')
                address = (
                    address_button.first.get_attribute("aria-label") or address_button.first.inner_text()
                    if address_button.count()
                    else ""
                )
                website_link = page.locator('a[data-item-id="authority"]')
                website = website_link.first.get_attribute("href") if website_link.count() else None
                report.update(observed_name=name, observed_address=address, observed_website=website)
                if not job.get("confirmed_place") and not identity_matches(
                    job["name"], job["address"], job["postcode"], name, address
                ):
                    report["status"] = "place_mismatch"
                    return report
                tab = page.get_by_role("tab", name=MENU)
                if not tab.count():
                    report["status"] = "menu_unavailable"
                    return report
                progress("进入菜单页签")
                tab.first.click()
                heading = page.get_by_role("heading", name=MENU).first
                heading.wait_for(timeout=15000)
                section = heading.locator("xpath=..").locator("xpath=..")
                cards = section.get_by_role("button", name=PHOTO)
                count = min(cards.count(), 5)
                report["thumbnail_count"] = cards.count()
                for index in range(count):
                    progress(f"获取菜单图片 {index + 1}/{count}")
                    cards.nth(index).click()
                    page.wait_for_function("location.href.includes('!6shttps:')", timeout=15000)
                    viewer = page.url
                    source = photo_url(viewer)
                    if source:
                        entry = download(source, out, proxy.replace("socks5://", "socks5h://"))
                        if entry["sha256"] not in {item["sha256"] for item in report["images"]}:
                            report["images"].append({**entry, "viewer_url": viewer})
                    if index + 1 < count:
                        page.go_back(wait_until="domcontentloaded")
                        heading.wait_for(timeout=15000)
                report["status"] = "downloaded" if report["images"] else "images_unavailable"
            finally:
                context.close()
    except BrowserTimeout:
        report["status"] = "timeout"
    except (BrowserError, httpx.HTTPError, ValueError):
        report["status"] = "failed"
    return report


def capture_with_fallback(
    job: dict,
    profile: Path,
    out: Path,
    proxy: str,
    force_headless: bool = False,
    progress: Callable[[str], None] = lambda _: None,
) -> dict:
    headless = job.get("headless", False) or force_headless
    report = capture(job, profile, out, proxy, headless, progress)
    attempts = [
        {
            "headless": headless,
            "status": report["status"],
            "observed_name": report.get("observed_name"),
            "observed_address": report.get("observed_address"),
            "observed_website": report.get("observed_website"),
        }
    ]
    # 仅无图片的视图/加载失败回退；验证码和目标不匹配不自动重试。
    if (
        headless
        and not force_headless
        and not report["images"]
        and report["status"] in {"limited_view", "menu_unavailable", "images_unavailable", "timeout", "failed"}
    ):
        progress("无头模式未获取菜单，使用显示浏览器模式重试一次")
        retry = capture(job, profile, out, proxy, False, progress)
        attempts.append(
            {
                "headless": False,
                "status": retry["status"],
                "observed_name": retry.get("observed_name"),
                "observed_address": retry.get("observed_address"),
                "observed_website": retry.get("observed_website"),
            }
        )
        report = retry
    report["attempts"] = attempts
    report["actual_headless"] = attempts[-1]["headless"]
    return report
