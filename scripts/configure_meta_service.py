#!/usr/bin/env python3
"""Create an internal Docker service secret without collecting social credentials."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "infra/secrets/meta-service-token"
path.parent.mkdir(parents=True, exist_ok=True)
if not path.exists():
    with path.open("x") as f:
        path.chmod(0o600)
        f.write(secrets.token_urlsafe(48) + "\n")
print("Meta 内部服务密钥已准备；未配置社媒账号，未发送消息。")
