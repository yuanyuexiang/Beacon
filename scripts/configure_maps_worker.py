"""为本机 Maps 执行器生成独立密钥，写入已忽略的配置；不显示密钥。"""

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATH = ROOT / "data/browser-profiles/maps-worker.token"


def main():
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    TOKEN_PATH.parent.chmod(0o700)
    token = TOKEN_PATH.read_text().strip() if TOKEN_PATH.exists() else secrets.token_urlsafe(48)
    if len(token) < 32:
        raise ValueError("现有执行器密钥过短，请更换")
    TOKEN_PATH.write_text(token + "\n")
    TOKEN_PATH.chmod(0o600)
    for path in (ROOT / "apps/api/.env", ROOT / "infra/.env"):
        if not path.exists():
            raise FileNotFoundError(f"请先按操作手册创建 {path.relative_to(ROOT)}")
        lines = path.read_text().splitlines()
        lines = [line for line in lines if not line.startswith("BEACON_MAPS_WORKER_TOKEN=")]
        path.write_text("\n".join(lines + ["BEACON_MAPS_WORKER_TOKEN=" + token]) + "\n")
        path.chmod(0o600)
    print("Maps 执行器密钥已配置；请重建 API 并启动执行器。密钥未显示。")


if __name__ == "__main__":
    main()
