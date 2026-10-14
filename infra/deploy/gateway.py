#!/usr/bin/env python3
"""Root-owned, forced-SSH deployment gateway. Input is one bounded JSON document.

The deployment identity can deploy trusted application images; it has no interactive shell.
Docker deployment is privileged. Repository write access and CI secrets remain trusted.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_SERVICES = ["api", "web", "gmail-service", "meta-service"]
WORKERS = ["gmail-worker", "outreach-worker", "maps-worker", "directory-worker"]
VOLUMES = ["beacon-data", "beacon-gmail-data", "beacon-meta-data", "beacon-maps-data"]
MAX_REQUEST = 32768
CREATE_ARGS = ["--no-build", "--pull", "never"]


class DeploymentError(RuntimeError):
    pass


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def validate_request(body, compose_hash, gateway_hash):
    if not isinstance(body, dict):
        raise DeploymentError("部署输入必须为对象")
    sha = body.get("sha", "")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise DeploymentError("提交 SHA 格式错误")
    for key in ("run_id", "run_number"):
        if type(body.get(key)) is not int or body[key] < 1:
            raise DeploymentError("工作流序号无效")
    if body.get("compose_sha256") != compose_hash or body.get("gateway_sha256") != gateway_hash:
        raise DeploymentError("服务器部署规范与仓库不同，需同步基础设施配置后重试")
    images = body.get("images")
    if not isinstance(images, dict) or set(images) != {"api", "web", "gmail", "meta", "maps"}:
        raise DeploymentError("发布必须包含五个镜像")
    for name, image in images.items():
        pattern = rf"ghcr\.io/yuanyuexiang/beacon-{name}@sha256:[0-9a-f]{{64}}"
        if not isinstance(image, str) or not re.fullmatch(pattern, image):
            raise DeploymentError("只允许本仓库的 GHCR 镜像 digest")
    compatibility = body.get("compatibility")
    if (
        not isinstance(compatibility, dict)
        or not isinstance(compatibility.get("migration_head"), str)
        or not re.fullmatch(r"[0-9a-f]{12}", compatibility["migration_head"])
    ):
        raise DeploymentError("迁移版本声明无效")
    prior = compatibility.get("rollback_compatible_from")
    if not isinstance(prior, list) or any(
        not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{12}", v) for v in prior
    ):
        raise DeploymentError("回滚兼容版本声明无效")
    if type(compatibility.get("provider_storage_compatible")) is not bool:
        raise DeploymentError("服务持久化格式兼容声明无效")
    if "directory_worker" in compatibility and type(compatibility["directory_worker"]) is not bool:
        raise DeploymentError("来源 worker 兼容声明无效")
    user, token = body.get("registry_user"), body.get("registry_token")
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_\[\]-]{1,100}", user):
        raise DeploymentError("镜像认证用户无效")
    if not isinstance(token, str) or not 1 <= len(token) <= 8192 or "\n" in token or "\x00" in token:
        raise DeploymentError("镜像短期凭据无效")
    # Never persist or log the registry token.
    return {
        key: body[key]
        for key in (
            "sha",
            "run_id",
            "run_number",
            "images",
            "compose_sha256",
            "gateway_sha256",
            "compatibility",
        )
    }


def rollback_allowed(old_revision, new_revision, compatibility):
    if not compatibility["provider_storage_compatible"]:
        return False
    if old_revision == new_revision:
        return True
    return new_revision == compatibility["migration_head"] and old_revision in compatibility["rollback_compatible_from"]


class Gateway:
    def __init__(self, root=Path("/opt/beacon")):
        self.root = Path(root)
        self.config = self.root / "config"
        self.state = self.root / "state"
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.settings = json.loads((self.config / "settings.json").read_text())
        self.docker_env = os.environ.copy()
        self.log_path = None

    def run(
        self,
        command,
        *,
        input_text=None,
        timeout=600,
        stdout_file=None,
        stdin_file=None,
    ):
        try:
            result = subprocess.run(
                command,
                input=input_text,
                stdin=stdin_file,
                text=stdout_file is None,
                stdout=stdout_file or subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.docker_env,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise DeploymentError("部署命令超时；请核对服务器发布记录") from None
        if self.log_path:
            with self.log_path.open("a") as stream:
                stream.write("command: " + " ".join(command) + "\n")
                # No compose config dump, registry stdin, environment or incoming request is logged.
                if stdout_file is None and result.stdout:
                    stream.write(result.stdout)
                if result.stderr:
                    stream.write(
                        result.stderr if isinstance(result.stderr, str) else result.stderr.decode(errors="replace")
                    )
        if result.returncode:
            raise DeploymentError("服务器命令失败：" + " ".join(command[:3]))
        return result.stdout if stdout_file is None else ""

    def compose(self, release, *args, timeout=600, stdout_file=None, stdin_file=None):
        return self.run(
            [
                "docker",
                "compose",
                "--project-name",
                "beacon",
                "--project-directory",
                str(self.root),
                "--env-file",
                str(self.config / "runtime.env"),
                "--env-file",
                str(release / "release.env"),
                "-f",
                str(self.root / "compose.yaml"),
                *args,
            ],
            timeout=timeout,
            stdout_file=stdout_file,
            stdin_file=stdin_file,
        )

    def revision(self, release):
        exists = self.compose(
            release,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "beacon",
            "-d",
            "beacon",
            "-Atc",
            "SELECT to_regclass('public.alembic_version') IS NOT NULL;",
        ).strip()
        if exists != "t":
            return None
        return (
            self.compose(
                release,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "beacon",
                "-d",
                "beacon",
                "-Atc",
                "SELECT version_num FROM alembic_version;",
            ).strip()
            or None
        )

    def health(self, manifest):
        domain = self.settings["domain"]
        last_error = None
        # First certificate issuance may include the configured 90s DNS propagation delay.
        for attempt in range(60):
            try:
                for path in ("/healthz", "/api/health"):
                    request = urllib.request.Request(
                        "https://" + domain + path,
                        headers={"Cache-Control": "no-cache"},
                    )
                    with urllib.request.urlopen(request, timeout=10) as response:
                        data = json.load(response)
                    if data.get("status") != "ok" or data.get("release") != manifest["sha"]:
                        raise DeploymentError("公网服务版本与候选发布不一致")
                return
            except (
                urllib.error.URLError,
                ValueError,
                DeploymentError,
                TimeoutError,
            ) as exc:
                last_error = type(exc).__name__
                if attempt < 59:
                    time.sleep(5)
        raise DeploymentError("HTTPS 或公网版本验证失败：" + str(last_error))

    def backup(self, release, manifest):
        folder = self.root / "backups" / release.name
        folder.mkdir(parents=True, exist_ok=False, mode=0o700)
        with (folder / "database.dump").open("wb") as stream:
            self.compose(
                release,
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                "beacon",
                "-Fc",
                "beacon",
                stdout_file=stream,
            )
        # Application writers and credential services are stopped before filesystem snapshots.
        for volume in VOLUMES:
            self.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--entrypoint",
                    "tar",
                    "-v",
                    volume + ":/source:ro",
                    "-v",
                    str(folder) + ":/backup",
                    manifest["images"]["api"],
                    "-czf",
                    "/backup/" + volume + ".tgz",
                    "-C",
                    "/source",
                    ".",
                ]
            )
        hashes = {p.name: file_hash(p) for p in folder.iterdir() if p.is_file()}
        atomic_json(folder / "checksums.json", hashes)
        with (folder / "database.dump").open("rb") as stream:
            self.compose(
                release,
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "--list",
                stdin_file=stream,
                timeout=60,
            )

    def prune_backups(self):
        folders = sorted(
            (
                p
                for p in (self.root / "backups").iterdir()
                if p.is_dir()
                and not p.is_symlink()
                and (p / "checksums.json").is_file()
                and re.fullmatch(r"[0-9]+-[0-9]+-[0-9a-f]{40}-[0-9a-f]{8}", p.name)
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for folder in folders[5:]:
            if folder.stat().st_mtime < time.time() - 14 * 86400:
                shutil.rmtree(folder)

    def start_apps(self, release):
        self.compose(
            release,
            "up",
            "-d",
            "--pull",
            "never",
            "--wait",
            "--wait-timeout",
            "240",
            *APP_SERVICES,
        )

    def workers_for(self, release):
        # 固定 Compose 会恢复旧镜像；旧 API 不支持来源 worker，不能启动它。
        path = release / "manifest.json"
        manifest = json.loads(path.read_text()) if path.exists() else {}
        names = list(WORKERS)
        if manifest.get("compatibility", {}).get("directory_worker") is not True:
            names.remove("directory-worker")
        return names

    def start_workers(self, release):
        self.compose(
            release,
            "up",
            "-d",
            "--pull",
            "never",
            "--wait",
            "--wait-timeout",
            "60",
            *self.workers_for(release),
        )

    def deploy(self, body):
        manifest = validate_request(body, file_hash(self.root / "compose.yaml"), file_hash(Path(__file__)))
        current_path, pending = self.state / "current.json", self.state / "pending.json"
        old = json.loads(current_path.read_text()) if current_path.exists() else None
        if old and manifest["run_number"] < old["run_number"]:
            return {"status": "skipped_stale", "sha": old["sha"]}
        if old and manifest["run_number"] == old["run_number"] and manifest["sha"] == old["sha"]:
            self.health(old)
            return {"status": "already_deployed", "sha": old["sha"]}
        if pending.exists():
            raise DeploymentError("存在未完成发布；需先核对 pending.json 和数据库，不能覆盖未确认状态")
        if shutil.disk_usage(self.root).free < self.settings.get("min_free_bytes", 5 * 1024**3):
            raise DeploymentError("服务器磁盘余量不足")
        release = (
            self.root
            / "releases"
            / f"{manifest['run_number']}-{manifest['run_id']}-{manifest['sha']}-{secrets.token_hex(4)}"
        )
        release.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json(release / "manifest.json", manifest)
        with (release / "release.env").open("w") as stream:
            for name, image in manifest["images"].items():
                stream.write(name.upper() + "_IMAGE=" + image + "\n")
            stream.write("BEACON_RELEASE_SHA=" + manifest["sha"] + "\n")
        self.log_path = release / "deploy.log"
        old_release = self.root / "releases" / old["release_dir"] if old else None
        manifest["release_dir"] = release.name
        touched = False
        old_revision = None
        with tempfile.TemporaryDirectory(prefix="beacon-registry-", dir=self.root) as docker_config:
            self.docker_env["DOCKER_CONFIG"] = docker_config
            try:
                self.compose(release, "config", "--quiet")
                self.run(["docker", "network", "inspect", "matrix-network"])
                self.run(
                    [
                        "docker",
                        "login",
                        "ghcr.io",
                        "--username",
                        body["registry_user"],
                        "--password-stdin",
                    ],
                    input_text=body["registry_token"] + "\n",
                    timeout=60,
                )
                self.compose(release, "pull", "postgres", *APP_SERVICES, "maps-worker")
                self.compose(
                    release,
                    "up",
                    "-d",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "120",
                    "postgres",
                )
                # D50 adds a worker without changing storage or schema. Supply its image
                # to the previous release so the new fixed Compose can also roll it back.
                if old_release and "maps" not in old["images"]:
                    with (old_release / "release.env").open("a") as stream:
                        stream.write("MAPS_IMAGE=" + manifest["images"]["maps"] + "\n")
                old_revision = self.revision(release)
                atomic_json(
                    pending,
                    {
                        "candidate": manifest,
                        "previous": old,
                        "phase": "stopping",
                        "old_revision": old_revision,
                    },
                )
                touched = True
                self.compose(
                    old_release or release,
                    "stop",
                    "--timeout",
                    "180",
                    *self.workers_for(release),
                    *APP_SERVICES,
                    timeout=1500,
                )
                # On a first deployment create stopped volume holders without starting app writers.
                self.compose(
                    release,
                    "create",
                    *CREATE_ARGS,
                    "api",
                    "gmail-service",
                    "meta-service",
                    "maps-worker",
                )
                self.backup(release, manifest)
                atomic_json(
                    pending,
                    {
                        "candidate": manifest,
                        "previous": old,
                        "phase": "migrating",
                        "old_revision": old_revision,
                    },
                )
                self.compose(release, "run", "--rm", "--no-deps", "migrate", timeout=600)
                if self.revision(release) != manifest["compatibility"]["migration_head"]:
                    raise DeploymentError("迁移后的数据库版本与发布声明不一致")
                self.start_apps(release)
                self.health(manifest)
                self.start_workers(release)
                if old:
                    atomic_json(self.state / "previous.json", old)
                atomic_json(current_path, manifest)
                pending.unlink()
                with contextlib.suppress(OSError):
                    self.prune_backups()
                return {"status": "deployed", "sha": manifest["sha"]}
            except Exception as exc:
                if touched:
                    # Never restore a database automatically or resume an unsafe old worker.
                    with contextlib.suppress(Exception):
                        self.compose(release, "stop", "--timeout", "180", *self.workers_for(release), timeout=400)
                    if old_release and rollback_allowed(
                        old_revision, self.revision(release), manifest["compatibility"]
                    ):
                        self.start_apps(old_release)
                        self.health(old)
                        self.start_workers(old_release)
                        pending.unlink(missing_ok=True)
                        atomic_json(
                            self.state / "last_failure.json",
                            {"sha": manifest["sha"], "rolled_back_to": old["sha"]},
                        )
                        raise DeploymentError("候选发布失败，已回滚上一版本；本次流水线仍标记失败") from None
                if isinstance(exc, DeploymentError):
                    raise
                raise DeploymentError("部署未完成，请核对服务器受控日志；未自动恢复数据库") from None
            finally:
                self.docker_env.pop("DOCKER_CONFIG", None)


def main():
    os.umask(0o077)
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise DeploymentError("部署请求过大")
        body = json.loads(raw)
        gateway = Gateway()
        with (gateway.state / "deploy.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = gateway.deploy(body)
        print(json.dumps(result))
    except (DeploymentError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "detail": str(exc) if isinstance(exc, DeploymentError) else "部署请求格式无效",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
