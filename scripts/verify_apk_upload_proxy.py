"""通过真实 Next rewrite 上传 12 MB，验证大小和哈希；不访问真实 API 或发布 APK。"""

import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        remaining = int(self.headers["Content-Length"])
        size = 0
        digest = hashlib.sha256()
        while remaining:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            size += len(chunk)
            remaining -= len(chunk)
            digest.update(chunk)
        result = json.dumps({"size": size, "sha256": digest.hexdigest()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)

    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> None:
    with ThreadingHTTPServer(("127.0.0.1", 0), Receiver) as backend:
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="beacon-apk-proxy-") as directory:
            fixture = Path(directory)
            shutil.copy(ROOT / "apps/web/next.config.ts", fixture)
            (fixture / "node_modules").symlink_to(ROOT / "apps/web/node_modules")
            (fixture / "package.json").write_text('{"private":true}')
            (fixture / "app").mkdir()
            (fixture / "app/page.js").write_text(
                'export default function Page(){return "probe"}'
            )
            (fixture / "app/layout.js").write_text(
                "export default function Layout({children}){return <html><body>{children}</body></html>}"
            )
            env = {
                **os.environ,
                "BEACON_API_URL": f"http://127.0.0.1:{backend.server_port}",
                "NEXT_TELEMETRY_DISABLED": "1",
            }
            with (fixture / "next.log").open("w+") as log:
                process = subprocess.Popen(
                    [
                        "node",
                        str(ROOT / "apps/web/node_modules/next/dist/bin/next"),
                        "dev",
                        "--port",
                        str(port),
                    ],
                    cwd=fixture,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    for _ in range(200):
                        try:
                            with socket.create_connection(
                                ("127.0.0.1", port), timeout=0.2
                            ):
                                break
                        except OSError:
                            if process.poll() is not None:
                                raise RuntimeError("Next 启动失败") from None
                            time.sleep(0.1)
                    body = b"Beacon proxy regression\n" * 550000
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", port, timeout=25
                    )
                    try:
                        connection.request(
                            "POST",
                            "/api/mobile/app/uploads",
                            body,
                            {"Content-Type": "application/vnd.android.package-archive"},
                        )
                        response = connection.getresponse()
                        actual = json.loads(response.read())
                        assert response.status == 200, response.status
                        assert actual == {
                            "size": len(body),
                            "sha256": hashlib.sha256(body).hexdigest(),
                        }, actual
                        print(
                            f"PASS: Next rewrite 完整转发 {len(body)} bytes，SHA-256 一致"
                        )
                    finally:
                        connection.close()
                except Exception:
                    log.seek(0)
                    print(log.read()[-4000:])
                    raise
                finally:
                    process.terminate()
                    process.wait(timeout=15)
        backend.shutdown()


if __name__ == "__main__":
    main()
