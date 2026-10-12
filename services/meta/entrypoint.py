"""Read Docker secret before dropping privileges; credentials belong to uid 10002."""

import os
from pathlib import Path

path = os.environ["META_SERVICE_TOKEN_FILE"]
token = Path(path).read_text().strip()
if len(token) < 32:
    raise RuntimeError("Meta 服务内部密钥至少 32 字符")
runtime = Path("/tmp/meta-service-token")
runtime.write_text(token)
runtime.chmod(0o600)
os.chown(runtime, 10002, 10002)
os.environ["META_SERVICE_TOKEN_FILE"] = str(runtime)
os.chown(os.environ.get("META_DATA_DIR", "/data"), 10002, 10002)
os.setgroups([])
os.setgid(10002)
os.setuid(10002)
os.execv("/srv/.venv/bin/uvicorn", ["uvicorn", "meta_service.server:app", "--host", "0.0.0.0", "--port", "8091"])
