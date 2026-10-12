"""Executed by the operator bootstrap over trusted admin SSH, never by CI."""

import base64
import fcntl
import json
import os
import pwd
import secrets
import subprocess
from pathlib import Path


def env_quote(value):
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def prepare_traefik(before):
    after = before.replace("--log.level=DEBUG", "--log.level=INFO")
    after = after.replace("--api.dashboard=true", "--api.dashboard=false")
    after = after.replace("traefik.enable=true", "traefik.enable=false")
    image = "traefik:v3.6.25@sha256:31267173a15b4944e797a76ffd9c419707c8d8b32fe5b610f80cd0cfa05f372d"
    if "traefik:v3.6.25@" not in after:
        after = after.replace("traefik:v3.6.25", image)
    if "\nnetworks:" not in after:
        after = after.replace("  traefik:\n", "  traefik:\n    networks: [matrix-network]\n", 1)
        after += "\nnetworks:\n  matrix-network:\n    external: true\n"
    return after


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise RuntimeError("Initial provisioning requires the operator's root access")
    body = json.loads(base64.b64decode("BOOTSTRAP_PAYLOAD"))
    root = Path("/opt/beacon")
    root.mkdir(mode=0o700, exist_ok=True)
    root.chmod(0o700)
    for name in ("config", "state", "releases", "backups"):
        (root / name).mkdir(mode=0o700, exist_ok=True)
    with (root / "state/deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / "state/pending.json").exists():
            raise RuntimeError("Unresolved deployment; reconcile before provisioning")
        provision(root, body)
    print("Server identity, configuration and Traefik network prepared; no application deployed by bootstrap.")


def provision(root, body):
    config = root / "config"
    (config / "secrets").mkdir(mode=0o700, exist_ok=True)
    (config / "settings.json").write_text(json.dumps({"domain": body["domain"], "min_free_bytes": 5 * 1024**3}))
    runtime = config / "runtime.env"
    if not runtime.exists():
        password = secrets.token_hex(24)
        values = {
            "BEACON_DOMAIN": body["domain"],
            "POSTGRES_PASSWORD": password,
            "BEACON_DATABASE_URL": "postgresql+psycopg://beacon:" + password + "@postgres:5432/beacon",
            "BEACON_SECRET_KEY": secrets.token_hex(32),
            "BEACON_BOOTSTRAP_OPERATOR": "admin",
            "BEACON_BOOTSTRAP_PASSWORD": secrets.token_urlsafe(32),
            "BEACON_LLM_PROVIDER": "fake",
        }
        values.update(body["application"])
        runtime.write_text("\n".join(key + "=" + env_quote(value) for key, value in values.items()) + "\n")
        runtime.chmod(0o600)
    for name in ("gmail", "meta"):
        token = config / "secrets" / (name + "-service-token")
        if not token.exists():
            token.write_text(secrets.token_urlsafe(48) + "\n")
            token.chmod(0o600)
    lib = Path("/usr/local/lib/beacon-deploy")
    lib.mkdir(parents=True, exist_ok=True, mode=0o755)
    for path, data, mode in (
        (root / "compose.yaml", body["compose"], 0o600),
        (lib / "gateway.py", body["gateway"], 0o755),
    ):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(data)
        temporary.chmod(mode)
        temporary.replace(path)
    try:
        user = pwd.getpwnam("beacon-deploy")
    except KeyError:
        subprocess.run(["useradd", "--create-home", "--shell", "/bin/sh", "--user-group", "beacon-deploy"], check=True)
        user = pwd.getpwnam("beacon-deploy")
    folder = Path(user.pw_dir) / ".ssh"
    folder.mkdir(mode=0o700, exist_ok=True)
    os.chown(folder, user.pw_uid, user.pw_gid)
    key_file = folder / "authorized_keys"
    key_file.write_text(
        'restrict,command="sudo -n /usr/bin/python3 /usr/local/lib/beacon-deploy/gateway.py" '
        + body["public_key"].strip()
        + "\n"
    )
    key_file.chmod(0o600)
    os.chown(key_file, user.pw_uid, user.pw_gid)
    sudo = config / "beacon-deploy.sudoers"
    sudo.write_text("beacon-deploy ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/lib/beacon-deploy/gateway.py\n")
    sudo.chmod(0o440)
    subprocess.run(["visudo", "-cf", str(sudo)], check=True, stdout=subprocess.DEVNULL)
    installed = Path("/etc/sudoers.d/beacon-deploy")
    installed.write_text(sudo.read_text())
    installed.chmod(0o440)
    if subprocess.run(["docker", "network", "inspect", "matrix-network"], capture_output=True, check=False).returncode:
        subprocess.run(["docker", "network", "create", "matrix-network"], check=True, stdout=subprocess.DEVNULL)
    infra = Path("/home/ubuntu/infrastructure/docker-compose.yaml")
    if infra.exists():
        before = infra.read_text()
        backup = root / "backups/infrastructure-before-d49.yaml"
        if not backup.exists():
            backup.write_text(before)
            backup.chmod(0o600)
        infra.write_text(prepare_traefik(before))
        infra.chmod(0o600)
        validation = subprocess.run(
            ["docker", "compose", "-f", str(infra), "config", "--quiet"], capture_output=True, check=False
        )
        if validation.returncode:
            infra.write_text(before)
            raise RuntimeError("Infrastructure validation failed; original file restored")
        subprocess.run(
            ["docker", "compose", "-f", str(infra), "up", "-d", "traefik"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        inspect = subprocess.run(
            ["docker", "inspect", "traefik", "--format", "{{json .NetworkSettings.Networks}}"],
            check=True,
            capture_output=True,
            text=True,
        )
        if "matrix-network" not in json.loads(inspect.stdout):
            subprocess.run(["docker", "network", "connect", "matrix-network", "traefik"], check=True)


if __name__ == "__main__":
    main()
