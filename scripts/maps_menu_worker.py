"""专用 Maps 浏览器执行器；仅主动连接 Beacon API，不监听远程浏览器端口。

从仓库根目录运行：
uv run --project apps/api --extra maps-worker python scripts/maps_menu_worker.py \
  --token-file data/browser-profiles/maps-worker.token
"""

import argparse
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.integrations.maps_menu_browser import capture  # noqa: E402


def execute(client, job, args):
    base = f"/api/internal/maps-menu/{job['lead_id']}/{job['run_id']}"

    def progress(stage):
        response = client.post(base + "/progress", json={"lease": job["lease"], "stage": stage})
        response.raise_for_status()

    with tempfile.TemporaryDirectory(prefix="maps-menu-", dir=args.temp_dir) as directory:
        report = capture(job, Path(args.profile), Path(directory), args.proxy, job.get("headless", True) or args.headless, progress)
        for image in report["images"]:
            progress("上传菜单图片")
            with Path(image["file"]).open("rb") as file:
                response = client.post(
                    base + "/images",
                    data={
                        "lease": job["lease"],
                        "source_url": image["source_url"],
                        "viewer_url": image["viewer_url"],
                        "observed_name": report["observed_name"],
                        "observed_address": report["observed_address"],
                        "observed_website": report.get("observed_website") or "",
                    },
                    files={"file": ("menu", file, image["content_type"])},
                )
                response.raise_for_status()
        response = client.post(
            base + "/finish",
            json={
                "lease": job["lease"],
                "capture_status": report["status"],
                "thumbnail_count": report.get("thumbnail_count", 0),
                "observed_name": report.get("observed_name"),
                "observed_address": report.get("observed_address"),
                "observed_website": report.get("observed_website"),
            },
        )
        response.raise_for_status()
        print(f"菜单任务结束：{report['status']}，获取 {len(report['images'])} 张图片", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--profile", default="data/browser-profiles/maps-menu-test")
    parser.add_argument("--temp-dir", default="data/maps-worker-tmp")
    parser.add_argument("--proxy", default="socks5h://127.0.0.1:7890")
    parser.add_argument("--headless", action="store_true", help="强制无头运行，忽略工作台显示浏览器开关")
    parser.add_argument("--once", action="store_true", help="领取并执行一项任务后退出，用于验证")
    args = parser.parse_args()
    target = urlsplit(args.api_base)
    if target.scheme != "https" and not (target.scheme == "http" and target.hostname in {"127.0.0.1", "localhost"}):
        parser.error("远程 API 必须使用 HTTPS")
    token_path = Path(args.token_file)
    if not token_path.is_file():
        parser.error("执行器密钥文件不存在；请按操作手册配置")
    token_path.chmod(0o600)
    token = token_path.read_text().strip()
    if len(token) < 32:
        parser.error("执行器密钥至少 32 字符")
    Path(args.temp_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
    print("Maps 菜单执行器启动；使用专用浏览器会话，等待工作台任务", flush=True)
    with httpx.Client(
        base_url=args.api_base, headers={"Authorization": "Bearer " + token}, trust_env=False, timeout=90
    ) as client:
        while True:
            job = None
            try:
                response = client.post("/api/internal/maps-menu/claim")
                response.raise_for_status()
                job = response.json()["job"]
                if job:
                    execute(client, job, args)
                    if args.once:
                        break
            except KeyboardInterrupt:
                break
            except Exception as error:
                # 不输出 headers、凭证或异常 URL；任务保留已入库文件，可超时重试。
                print(f"执行器请求或任务失败：{type(error).__name__}", flush=True)
                if job:
                    with suppress(httpx.HTTPError):
                        client.post(
                            f"/api/internal/maps-menu/{job['lead_id']}/{job['run_id']}/finish",
                            json={"lease": job["lease"], "capture_status": "failed"},
                        )
                    if args.once:
                        break
            time.sleep(3)


if __name__ == "__main__":
    main()
