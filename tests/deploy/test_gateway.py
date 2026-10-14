import json
from pathlib import Path

import pytest

from infra.deploy import gateway
from infra.deploy.gateway import (
    DeploymentError,
    Gateway,
    atomic_json,
    file_hash,
    rollback_allowed,
    validate_request,
)


def request():
    return {
        "sha": "b" * 40,
        "run_id": 22,
        "run_number": 2,
        "images": {
            name: f"ghcr.io/yuanyuexiang/beacon-{name}@sha256:" + "c" * 64
            for name in ("api", "web", "gmail", "meta", "maps")
        },
        "compose_sha256": "compose",
        "gateway_sha256": "gateway",
        "registry_user": "yuanyuexiang",
        "registry_token": "ephemeral-do-not-persist",
        "compatibility": {
            "migration_head": "f9496c930a01",
            "rollback_compatible_from": [],
            "provider_storage_compatible": True,
        },
    }


class FakeGateway(Gateway):
    def __init__(self, root, *, failure=None, changed_schema=False):
        (root / "config").mkdir(parents=True)
        (root / "config/settings.json").write_text('{"domain":"beacon.example.test","min_free_bytes":0}')
        (root / "compose.yaml").write_text("services: {}")
        super().__init__(root)
        self.calls = []
        self.failure = failure
        self.schema = "f9496c930a01"
        self.changed_schema = changed_schema
        old = request()
        old.update(sha="a" * 40, run_number=1, run_id=11, release_dir="previous")
        old.pop("registry_token")
        old.pop("registry_user")
        (root / "releases/previous").mkdir(parents=True)
        (root / "releases/previous/release.env").write_text("old-images")
        atomic_json(self.state / "current.json", old)

    def run(self, command, **kwargs):
        self.calls.append(command)
        if self.failure == "pull" and "pull" in command:
            raise DeploymentError("pull failed")
        if "migrate" in command and self.changed_schema:
            self.schema = "b293fd7bd071"
        return ""

    def revision(self, _):
        return self.schema

    def backup(self, release, manifest):
        self.calls.append(["backup"])
        if self.failure == "backup":
            raise DeploymentError("backup failed")

    def health(self, manifest):
        self.calls.append(["health", manifest["sha"]])
        if self.failure == "health" and manifest["sha"] == "b" * 40:
            raise DeploymentError("candidate unhealthy")

    def body(self):
        body = request()
        body["compose_sha256"] = file_hash(self.root / "compose.yaml")
        body["gateway_sha256"] = file_hash(Path(gateway.__file__))
        if self.changed_schema:
            body["compatibility"]["migration_head"] = "b293fd7bd071"
        return body


def test_validate_only_fixed_registry_digests_and_never_returns_token():
    body = request()
    result = validate_request(body, "compose", "gateway")
    assert "registry_token" not in result and "registry_user" not in result
    body["images"]["api"] = "evil.io/application:latest"
    with pytest.raises(DeploymentError):
        validate_request(body, "compose", "gateway")


@pytest.mark.parametrize(
    "key,value",
    [
        ("sha", "main;touch /tmp/bad"),
        ("run_number", True),
        ("registry_token", "secret\ncommand"),
        ("compose_sha256", "changed"),
    ],
)
def test_invalid_request_fails_before_remote_operations(key, value):
    body = request()
    body[key] = value
    with pytest.raises(DeploymentError):
        validate_request(body, "compose", "gateway")


def test_pull_failure_keeps_old_apps_and_state(tmp_path):
    g = FakeGateway(tmp_path, failure="pull")
    with pytest.raises(DeploymentError):
        g.deploy(g.body())
    assert not any("stop" in c for c in g.calls)
    assert not (g.state / "pending.json").exists()
    assert json.loads((g.state / "current.json").read_text())["sha"] == "a" * 40
    assert not list(tmp_path.glob("beacon-registry-*"))


def test_backup_failure_recovers_previous_without_migration(tmp_path):
    g = FakeGateway(tmp_path, failure="backup")
    with pytest.raises(DeploymentError, match="已回滚"):
        g.deploy(g.body())
    assert not any("migrate" in c for c in g.calls)
    assert not (g.state / "pending.json").exists()
    assert json.loads((g.state / "current.json").read_text())["sha"] == "a" * 40


def test_unhealthy_candidate_rolls_back_and_reports_failure(tmp_path):
    g = FakeGateway(tmp_path, failure="health")
    with pytest.raises(DeploymentError, match="已回滚"):
        g.deploy(g.body())
    assert ["health", "a" * 40] in g.calls
    assert json.loads((g.state / "last_failure.json").read_text())["rolled_back_to"] == "a" * 40
    assert not (g.state / "pending.json").exists()
    assert "ephemeral-do-not-persist"
    for path in g.root.rglob("*.json"):
        assert "ephemeral-do-not-persist" not in path.read_text()


def test_changed_schema_does_not_blindly_restore_old_workers(tmp_path):
    g = FakeGateway(tmp_path, failure="health", changed_schema=True)
    with pytest.raises(DeploymentError):
        g.deploy(g.body())
    assert (g.state / "pending.json").exists()
    assert ["health", "a" * 40] not in g.calls
    assert not any("up" in c and "gmail-worker" in c for c in g.calls)


def test_success_records_version_then_workers_and_cleans_short_token(tmp_path):
    g = FakeGateway(tmp_path)
    result = g.deploy(g.body())
    assert result == {"status": "deployed", "sha": "b" * 40}
    assert not (g.state / "pending.json").exists()
    assert json.loads((g.state / "previous.json").read_text())["sha"] == "a" * 40
    assert json.loads((g.state / "current.json").read_text())["sha"] == "b" * 40
    assert not list(tmp_path.glob("beacon-registry-*"))
    assert any("up" in c and "gmail-worker" in c for c in g.calls)


def test_stale_release_and_pending_do_not_start_deploy(tmp_path):
    g = FakeGateway(tmp_path)
    body = g.body()
    body["run_number"] = 1
    body["sha"] = "a" * 40
    assert g.deploy(body)["status"] == "already_deployed"
    atomic_json(g.state / "pending.json", {"phase": "migrating"})
    with pytest.raises(DeploymentError, match="未完成"):
        g.deploy(g.body())


def test_schema_compatibility_must_be_explicit_and_provider_format_safe():
    value = request()["compatibility"]
    assert rollback_allowed("old", "old", value)
    assert not rollback_allowed("old", "f9496c930a01", value)
    value["rollback_compatible_from"] = ["old"]
    assert rollback_allowed("old", "f9496c930a01", value)
    value["provider_storage_compatible"] = False
    assert not rollback_allowed("old", "old", value)


def test_initial_infrastructure_preserves_certificates_and_is_idempotent():
    from infra.deploy.bootstrap_remote import prepare_traefik

    before = (
        "services:\n  traefik:\n    image: traefik:v3.6.25\n"
        '    command: ["--log.level=DEBUG", "--api.dashboard=true"]\n'
        '    volumes: ["./data/traefik/letsencrypt:/letsencrypt"]\n'
    )
    result = prepare_traefik(before)
    assert result.count("networks: [matrix-network]") == 1
    assert "\nnetworks:\n  matrix-network:\n    external: true\n" in result
    assert "--api.dashboard=false" in result and "--log.level=INFO" in result
    assert "./data/traefik/letsencrypt:/letsencrypt" in result
    assert prepare_traefik(result) == result


def test_runtime_secret_quoting_preserves_dollars_backslashes_and_quotes():
    from io import StringIO

    from dotenv import dotenv_values

    from infra.deploy.bootstrap_remote import env_quote

    value = "secret$literal\\path'quote"
    assert dotenv_values(stream=StringIO("TOKEN=" + env_quote(value) + "\n"))["TOKEN"] == value


def test_actual_create_command_is_accepted_by_compose_cli(tmp_path):
    import subprocess

    g = FakeGateway(tmp_path)
    g.deploy(g.body())
    command = next(command for command in g.calls if "create" in command)
    options = command[command.index("create") + 1 :]
    subprocess.run(["docker", "compose", "create", *options, "--help"], capture_output=True, check=True)


def test_upgrade_supplies_maps_image_to_previous_release_for_rollback(tmp_path):
    g = FakeGateway(tmp_path)
    previous = json.loads((g.state / "current.json").read_text())
    previous["images"].pop("maps")
    atomic_json(g.state / "current.json", previous)
    g.deploy(g.body())
    assert (
        "MAPS_IMAGE=ghcr.io/yuanyuexiang/beacon-maps@sha256:" in (g.root / "releases/previous/release.env").read_text()
    )
    assert "maps-worker" in gateway.WORKERS
    assert "beacon-maps-data" in gateway.VOLUMES


def test_directory_worker_is_started_only_for_supported_api_release(tmp_path):
    g = FakeGateway(tmp_path)
    old = g.root / "releases/previous"
    assert "directory-worker" not in g.workers_for(old)
    new = g.root / "releases/new"
    new.mkdir()
    atomic_json(new / "manifest.json", {"compatibility": {"directory_worker": True}})
    assert "directory-worker" in g.workers_for(new)


def test_backup_failure_does_not_start_directory_worker_with_old_api(tmp_path):
    g = FakeGateway(tmp_path, failure="backup")
    body = g.body()
    body["compatibility"]["directory_worker"] = True
    with pytest.raises(DeploymentError):
        g.deploy(body)
    worker_commands = [c for c in g.calls if "up" in c and "gmail-worker" in c]
    assert worker_commands and all("directory-worker" not in c for c in worker_commands)
