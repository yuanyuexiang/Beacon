"""Prepare an ignored service secret and optionally import existing OPC OAuth credentials.
Never prints credentials. No email is sent.
"""
import argparse
import json
import secrets
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--import-opc", action="store_true")
args = parser.parse_args()
secret_dir = root / "infra/secrets"
secret_dir.mkdir(mode=0o700, exist_ok=True)
secret_dir.chmod(0o700)
path = secret_dir / "gmail-service-token"
if not path.exists():
    path.write_text(secrets.token_urlsafe(48))
path.chmod(0o600)
print("Gmail service secret prepared (existing secret preserved)")
if args.import_opc:
    source = Path.home() / ".config/opc-business-os/gmail"
    credentials = json.loads((source / "credentials.json").read_text())
    token = json.loads((source / "token.json").read_text())
    if not token.get("refresh_token") or "gmail.send" not in token.get("scope", ""):
        raise SystemExit("Existing OAuth token lacks refresh token or send scope; not imported")
    # 密钥仅通过 stdin 进入容器，不写镜像或命令参数。
    payload = json.dumps({"credentials": credentials, "token": token}).encode()
    command = ["docker", "compose", "-f", str(root / "infra/docker-compose.yml"), "exec", "-T", "gmail-service",
               "python", "-c", '''import json,sys,urllib.request
from pathlib import Path
secret=Path('/run/secrets/gmail_service_token').read_text().strip()
req=urllib.request.Request('http://127.0.0.1:8090/auth/import',data=sys.stdin.buffer.read(),headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=20) as response:
 result=json.load(response)
print(json.dumps({k:result.get(k) for k in ['credentials_present','token_present','send_authorized','readonly_authorized']}))''']
    subprocess.run(command, input=payload, check=True)
