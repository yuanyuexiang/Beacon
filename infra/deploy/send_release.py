#!/usr/bin/env python3
"""CI-side manifest validation and SSH transport. Secrets stay in env/stdin."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def main():
    root = Path.cwd()
    prefix = "ghcr.io/yuanyuexiang/beacon-"
    images = {}
    for name in ("api", "web", "gmail", "meta"):
        value = json.loads((root / "images" / (name + ".json")).read_text())
        image = value["image"]
        if not re.fullmatch(re.escape(prefix + name) + r"@sha256:[0-9a-f]{64}", image):
            raise ValueError("镜像清单无效")
        images[name] = image
    host = os.environ["DEPLOY_HOST"]
    user = os.environ["DEPLOY_USER"]
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or user != "beacon-deploy":
        raise ValueError("服务器连接配置无效")
    manifest = {
        "sha": os.environ["GITHUB_SHA"],
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_number": int(os.environ["GITHUB_RUN_NUMBER"]),
        "images": images,
        "compose_sha256": hashlib.sha256((root / "infra/docker-compose.production.yaml").read_bytes()).hexdigest(),
        "gateway_sha256": hashlib.sha256((root / "infra/deploy/gateway.py").read_bytes()).hexdigest(),
        "compatibility": json.loads((root / "infra/deploy/compatibility.json").read_text()),
        "registry_user": os.environ["GITHUB_ACTOR"],
        "registry_token": os.environ["REGISTRY_TOKEN"],
    }
    with tempfile.TemporaryDirectory(prefix="beacon-ssh-") as folder:
        key, hosts = Path(folder) / "key", Path(folder) / "known_hosts"
        for path, value in (
            (key, os.environ["DEPLOY_SSH_KEY"]),
            (hosts, os.environ["DEPLOY_KNOWN_HOSTS"]),
        ):
            path.write_text(value + "\n")
            path.chmod(0o600)
        command = [
            "ssh",
            "-i",
            str(key),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile=" + str(hosts),
            "-o",
            "ConnectTimeout=20",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=10",
            user + "@" + host,
            "deploy",
        ]
        result = subprocess.run(
            command,
            input=json.dumps(manifest),
            text=True,
            capture_output=True,
            timeout=2400,
        )
        # Gateway returns only controlled status, never echoes the request or registry credentials.
        print(result.stdout)
        if result.returncode:
            print("SSH 或服务器发布失败；请查看部署记录。")
            raise SystemExit(result.returncode)
        outcome = json.loads(result.stdout.strip())
        verify = outcome.get("status") in {"deployed", "already_deployed"}
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a") as stream:
                stream.write("verify_release=" + str(verify).lower() + "\n")


if __name__ == "__main__":
    main()
