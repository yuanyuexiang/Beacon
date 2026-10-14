#!/usr/bin/env python3
"""CI validates production Compose without secrets or a deployment host."""

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path


def migration_head(root):
    revisions, parents = set(), set()
    for path in (root / "apps/api/migrations/versions").glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "revision",
                        "down_revision",
                    }:
                        value = ast.literal_eval(node.value)
                        if target.id == "revision":
                            revisions.add(value)
                        elif isinstance(value, str):
                            parents.add(value)
                        elif isinstance(value, tuple):
                            parents.update(value)
    heads = revisions - parents
    if len(heads) != 1:
        raise ValueError("发布要求单一 Alembic head")
    return heads.pop()


def main():
    root = Path.cwd()
    spec = importlib.util.spec_from_file_location("deploy_gateway", root / "infra/deploy/gateway.py")
    assert spec and spec.loader
    gateway = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gateway)
    subprocess.run(["docker", "compose", "create", *gateway.CREATE_ARGS, "--help"], capture_output=True, check=True)
    compatibility = json.loads((root / "infra/deploy/compatibility.json").read_text())
    if compatibility["migration_head"] != migration_head(root):
        raise ValueError("新增迁移后需更新 compatibility.json，并明确回滚兼容范围")
    with tempfile.TemporaryDirectory(prefix="beacon-compose-") as folder:
        config = Path(folder)
        (config / "secrets").mkdir()
        (config / "runtime.env").write_text("BEACON_LLM_PROVIDER=fake\n")
        for name in ("gmail", "meta", "maps"):
            if name == "maps":
                (config / "secrets/maps-worker-token").write_text("ci-not-a-real-secret-" * 3)
                continue
            (config / "secrets" / (name + "-service-token")).write_text("ci-not-a-real-secret-" * 3)
        env = {
            **os.environ,
            "BEACON_CONFIG_DIR": folder,
            "BEACON_DOMAIN": "beacon.example.test",
            "POSTGRES_PASSWORD": "ci-only",
            "BEACON_DATABASE_URL": "postgresql+psycopg://beacon:ci-only@postgres/beacon",
            "BEACON_SECRET_KEY": "ci-not-a-real-session-secret-0123456789",
            "BEACON_RELEASE_SHA": "a" * 40,
        }
        for name in ("api", "web", "gmail", "meta", "maps"):
            env[name.upper() + "_IMAGE"] = f"ghcr.io/yuanyuexiang/beacon-{name}@sha256:" + "a" * 64
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(root / "infra/docker-compose.production.yaml"),
                "config",
                "--format",
                "json",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        compose = json.loads(result.stdout)
        for name, service in compose["services"].items():
            assert not service.get("ports"), name + " must not publish host ports"
            assert not service.get("build"), name + " must use release images"
        assert compose["networks"]["ingress"]["external"]
        assert compose["networks"]["ingress"]["name"] == "matrix-network"
        assert "alembic" not in compose["services"]["api"]["command"]
    print("Production Compose, secret isolation and migration declaration checked.")
    print(
        "Compose SHA256:",
        hashlib.sha256((root / "infra/docker-compose.production.yaml").read_bytes()).hexdigest(),
    )


if __name__ == "__main__":
    main()
