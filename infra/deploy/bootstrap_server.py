#!/usr/bin/env python3
"""Operator-only initial provisioning. Uses an existing trusted admin SSH key.

No private key, application secret or registry token is printed or sent to GitHub.
Run with: uv run --project apps/api python infra/deploy/bootstrap_server.py --key Beacon.pem
"""

import argparse
import base64
import json
import subprocess
from pathlib import Path

from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--host", default="18.175.156.130")
    parser.add_argument("--domain", default="beacon.ai-onestep.com")
    parser.add_argument("--user", default="ubuntu")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    ci_key = root / "data/devops/beacon-deploy-key"
    if not ci_key.exists():
        ci_key.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "beacon-github-actions-deploy", "-f", str(ci_key)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    existing = dotenv_values(root / "infra/.env")
    allowed = (
        "BEACON_LLM_PROVIDER",
        "BEACON_LLM_MODEL",
        "BEACON_LLM_THINKING",
        "BEACON_DEEPSEEK_API_KEY",
        "BEACON_GOOGLE_PLACES_API_KEY",
        "BEACON_COMPANIES_HOUSE_API_KEY",
        "BEACON_EXA_API_KEY",
        "BEACON_ANTHROPIC_API_KEY",
    )
    application = {key: existing[key] for key in allowed if existing.get(key)}
    if any("\n" in value or "\r" in value for value in application.values()):
        raise ValueError("Application configuration must be single-line")
    body = {
        "domain": args.domain,
        "public_key": ci_key.with_suffix(".pub").read_text(),
        "application": application,
        "compose": (root / "infra/docker-compose.production.yaml").read_text(),
        "gateway": (root / "infra/deploy/gateway.py").read_text(),
    }
    script = (
        (root / "infra/deploy/bootstrap_remote.py")
        .read_text()
        .replace("BOOTSTRAP_PAYLOAD", base64.b64encode(json.dumps(body).encode()).decode())
    )
    command = [
        "ssh",
        "-i",
        str(args.key),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        args.user + "@" + args.host,
        "sudo",
        "-n",
        "python3",
        "-",
    ]
    result = subprocess.run(command, input=script, text=True, capture_output=True, timeout=300, check=False)
    print(result.stdout)
    if result.returncode:
        print("Server provisioning failed; credentials were not printed.")
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
