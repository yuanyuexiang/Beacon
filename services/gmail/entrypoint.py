"""Copy root-readable Compose secret, then run the service without root privileges."""
import os
from pathlib import Path

source = Path(os.environ.get("GMAIL_SERVICE_TOKEN_FILE", "/run/secrets/gmail_service_token"))
target = Path("/data/service-access-token")
target.write_bytes(source.read_bytes())
target.chmod(0o600)
os.chown(target, 10001, 10001)
os.environ["GMAIL_SERVICE_TOKEN_FILE"] = str(target)
os.setgid(10001)
os.setuid(10001)
os.execv("/srv/.venv/bin/uvicorn", ["uvicorn", "gmail_service.server:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"])
