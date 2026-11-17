# /// script
# requires-python = ">=3.12"
# dependencies = ["qrcode>=8,<9"]
# ///
"""Local-only Android wireless debugging QR pairing; never exposed by Beacon cloud."""

import io
import json
import secrets
import shutil
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import qrcode
import qrcode.image.svg


def adb(*args):
    result = subprocess.run(
        ["adb", *args], capture_output=True, text=True, timeout=20, check=False
    )
    return (result.stdout + result.stderr).strip()


def services(output):
    return [
        parts
        for line in output.splitlines()
        if len(parts := line.replace("\\t", " ").split()) == 3
        and parts[1].startswith("_adb-")
    ]


def main():
    if not shutil.which("adb"):
        raise SystemExit("未找到 adb，请先安装 Android platform-tools。")
    name = "studio-" + secrets.token_hex(5)
    password = secrets.token_hex(10)
    qr = qrcode.make(
        f"WIFI:T:ADB;S:{name};P:{password};;",
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    buffer = io.BytesIO()
    qr.save(buffer)
    state = {"message": "等待手机扫描二维码", "devices": "", "paired": False}
    lock = threading.Lock()
    stopped = threading.Event()
    deadline = time.monotonic() + 300
    paired_host = None

    def worker():
        nonlocal paired_host
        attempted = set()
        while not stopped.wait(2):
            try:
                devices = adb("devices", "-l")
                with lock:
                    state["devices"] = devices
                if not state["paired"] and time.monotonic() > deadline:
                    with lock:
                        state["message"] = "二维码已过期，请关闭窗口后重新打开入口。"
                    continue
                discovered = services(adb("mdns", "services"))
                if paired_host:
                    for _, kind, address in discovered:
                        if (
                            kind == "_adb-tls-connect._tcp"
                            and address.rsplit(":", 1)[0] == paired_host
                        ):
                            adb("connect", address)
                for instance, kind, address in discovered:
                    if (
                        instance != name
                        or kind != "_adb-tls-pairing._tcp"
                        or address in attempted
                    ):
                        continue
                    attempted.add(address)
                    with lock:
                        state["message"] = "已发现手机，正在配对…"
                    result = adb("pair", address, password)
                    if "Successfully paired" in result:
                        paired_host = address.rsplit(":", 1)[0]
                    with lock:
                        state["paired"] = "Successfully paired" in result
                        state["message"] = (
                            "配对成功，ADB 将自动连接；请查看下方设备列表。"
                            if state["paired"]
                            else "配对失败，请重新打开入口再扫码；检查局域网与 VPN。"
                        )
            except (OSError, subprocess.TimeoutExpired):
                with lock:
                    state["message"] = (
                        "ADB 响应超时，请检查无线调试、同一 Wi-Fi 和 VPN 局域网绕过设置。"
                    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path == "/status":
                with lock:
                    body = json.dumps(state, ensure_ascii=False).encode()
                content_type = "application/json"
            elif self.path == "/qr.svg":
                body, content_type = buffer.getvalue(), "image/svg+xml"
            elif self.path == "/":
                body = """<!doctype html><meta charset="utf-8"><title>Beacon · 无线连接手机</title>
<style>body{font:16px system-ui;background:#f7f5f2;color:#282522;margin:40px auto;max-width:680px}main{background:white;padding:32px;border-radius:20px}img{width:300px;max-width:100%}h1{font-size:26px}pre{white-space:pre-wrap;background:#f7f5f2;padding:16px;border-radius:10px}#status{color:#b60010;font-weight:bold}</style>
<main><h1>无线连接手机</h1><p>手机和电脑连接同一 Wi-Fi。在手机打开：</p><p><b>开发者选项 → 无线调试 → 扫描二维码配对设备</b></p><img src="/qr.svg"><p id="status">等待扫码</p><p>二维码 5 分钟有效。配对后设备列表显示 device 才表示已连接，可用于安装与测试 App。</p><pre id="devices"></pre><p>这是 Android 调试配对，不是 Beacon 平台配对。无需 USB 或 Android Studio；没有发现手机时，请检查 VPN 和路由器设备隔离。</p><p>结束后关闭启动它的终端，或按 Ctrl+C。</p></main>
<script>async function poll(){try{let s=await(await fetch('/status')).json();document.getElementById('status').textContent=s.message;document.getElementById('devices').textContent=s.devices}catch{document.getElementById('status').textContent='本地连接工具已停止'}}setInterval(poll,2000);poll()</script>""".encode()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=worker, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"无线连接手机：{url}（按 Ctrl+C 结束）", flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.server_close()


if __name__ == "__main__":
    main()
