"""Release permissions, atomic upload, signature pinning and APK-only download links; no installation."""

import base64
import io
import json
import subprocess
import time
import uuid
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import AuditLog, Operator
from app.modules.mobile import apktools
from app.modules.mobile import app_releases as releases
from tests.test_auth import make_operator
from tests.test_imports import login
from tests.test_users import session


def apk(payload=b"first"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
        archive.writestr("classes.dex", payload)
    return buffer.getvalue()


@pytest.fixture
def setup_release(client, db, monkeypatch, tmp_path):
    login(client, db)
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setattr(apktools, "available", lambda: True)
    metadata = {"package": apktools.PACKAGE, "version_code": 1, "version_name": "1.0.0", "signer_sha256": "a" * 64}
    monkeypatch.setattr(apktools, "inspect", lambda _: dict(metadata))
    return metadata


def upload(client, body=None):
    return client.post(
        "/api/mobile/app/uploads",
        content=body if body is not None else apk(),
        headers={"Content-Type": "application/vnd.android.package-archive"},
    )


def publish(client, item, current=None, **fields):
    return client.post(
        f"/api/mobile/app/{item['id']}/publish", json={"expected_current_id": current, "notes": "Updated app", **fields}
    )


def token_for(data):
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return payload + "." + releases.token_signature(payload)


def test_upload_needs_explicit_publish_and_signed_download_is_pinned(client, db, setup_release):
    assert client.get("/api/mobile/app").json()["current"] is None
    response = upload(client)
    assert response.status_code == 201, response.text
    first = response.json()
    assert client.get(f"/api/files/mobile-apps/{first['sha256']}.apk").status_code == 404
    assert client.get("/api/mobile/app").json()["current"] is None
    assert client.post("/api/mobile/app/download-link").status_code == 404
    assert publish(client, first).status_code == 200
    link = client.post("/api/mobile/app/download-link").json()["path"]
    # A phone with no browser session can download only this published APK.
    client.cookies.clear()
    downloaded = client.get(link)
    assert downloaded.status_code == 200 and downloaded.content == apk()
    assert downloaded.headers["content-type"] == "application/vnd.android.package-archive"
    assert "attachment" in downloaded.headers["content-disposition"]
    assert "no-store" in downloaded.headers["cache-control"]
    assert downloaded.headers["x-checksum-sha256"] == first["sha256"]
    partial = client.get(link, headers={"Range": "bytes=0-3"})
    assert partial.status_code == 206 and partial.content == apk()[:4]
    assert client.get(link + "x").status_code == 403
    assert client.get(link.replace(first["id"], str(uuid.uuid4()), 1)).status_code == 403
    assert client.get("/api/mobile/app").status_code == 401
    assert client.post("/api/mobile/app/uploads", content=apk()).status_code == 401


@pytest.mark.parametrize("role", ["member", "director", "viewer"])
def test_role_permissions(client, db, setup_release, role):
    item = upload(client).json()
    assert publish(client, item).status_code == 200
    user = make_operator(db, "download-" + role)
    user.role = role
    db.commit()
    member = session(user)
    assert member.get("/api/mobile/app").json()["drafts"] == []
    assert member.post("/api/mobile/app/uploads", content=apk()).status_code == 403
    assert (
        member.post(f"/api/mobile/app/{item['id']}/publish", json={"expected_current_id": item["id"]}).status_code
        == 403
    )
    assert member.post("/api/mobile/app/download-link").status_code == (403 if role == "viewer" else 200)


def test_signature_pin_conflicts_and_rollback(client, db, setup_release):
    metadata = setup_release
    first = upload(client).json()
    assert publish(client, first).status_code == 200
    old_link = client.post("/api/mobile/app/download-link").json()["path"]
    metadata.update(version_code=2, version_name="1.1.0")
    second = upload(client, apk(b"second")).json()
    assert publish(client, second).status_code == 409  # stale page must not replace the current release
    assert publish(client, second, first["id"]).status_code == 200
    catalog = client.get("/api/mobile/app").json()
    assert catalog["current"]["id"] == second["id"] and catalog["previous"]["id"] == first["id"]
    assert client.get(old_link).content == apk()  # an issued QR never changes its file underneath the user
    assert publish(client, first, second["id"]).status_code == 409
    assert publish(client, first, second["id"], rollback=True).status_code == 200
    assert client.get("/api/mobile/app").json()["current"]["id"] == first["id"]
    metadata["signer_sha256"] = "b" * 64
    assert upload(client, apk(b"different key")).status_code == 409
    assert not list(releases.directory().glob("upload-*"))
    assert client.get("/api/mobile/app").json()["current"]["id"] == first["id"]


def test_pending_apk_signed_before_first_publish_is_rechecked(client, db, setup_release):
    first = upload(client).json()
    setup_release["signer_sha256"] = "b" * 64
    other = upload(client, apk(b"other signer")).json()
    assert publish(client, first).status_code == 200
    assert publish(client, other, first["id"]).status_code == 409


def test_oversized_empty_invalid_upload_and_missing_file_preserve_current(client, db, setup_release, monkeypatch):
    first = upload(client).json()
    assert publish(client, first).status_code == 200
    assert upload(client, b"").status_code == 422
    monkeypatch.setattr(releases, "MAX_BYTES", 8)
    assert upload(client, b"123456789").status_code == 413
    # Also enforce the streamed length when no Content-Length is supplied.
    response = client.post("/api/mobile/app/uploads", content=iter([b"12345", b"67890"]))
    assert response.status_code == 413
    assert not list(releases.directory().glob("upload-*"))
    monkeypatch.setattr(releases, "MAX_BYTES", 256 * 1024**2)

    def invalid(_):
        raise HTTPException(422, "Invalid APK")

    monkeypatch.setattr(apktools, "inspect", invalid)
    assert upload(client, b"not an apk").status_code == 422
    assert not list(releases.directory().glob("upload-*"))
    assert client.get("/api/mobile/app").json()["current"]["id"] == first["id"]
    releases.artifact(first).unlink()
    assert client.post("/api/mobile/app/download-link").status_code == 409


def test_duplicate_upload_does_not_duplicate_release(client, db, setup_release):
    first, second = upload(client).json(), upload(client).json()
    assert first["id"] == second["id"]
    assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "mobile_app_uploaded")))) == 1


def test_expired_revoked_issuer_and_unpublished_links_are_rejected(client, db, setup_release):
    first = upload(client).json()
    assert publish(client, first).status_code == 200
    issuer = db.scalar(select(Operator).where(Operator.username == "tester"))
    fields = {
        "release_id": first["id"],
        "issuer": str(issuer.id),
        "session_version": issuer.session_version,
        "expires": int(time.time()) + 600,
    }
    path = f"/api/mobile/app-download/{first['id']}?token="
    assert client.get(path + token_for({**fields, "expires": int(time.time()) - 1})).status_code == 403
    assert client.get(path + token_for({**fields, "session_version": issuer.session_version + 1})).status_code == 403
    assert client.get(path + "not-a-token").status_code == 403
    issuer.is_active = False
    db.commit()
    assert client.get(path + token_for(fields)).status_code == 403
    issuer.is_active = True
    db.commit()
    setup_release["version_code"] = 2
    pending = upload(client, apk(b"unpublished")).json()
    assert (
        client.get(
            f"/api/mobile/app-download/{pending['id']}?token=" + token_for({**fields, "release_id": pending["id"]})
        ).status_code
        == 404
    )


@pytest.mark.parametrize("prefix", ["Signer #1", "V2 Signer:"])
def test_apk_inspector_verifies_signatures_and_package(tmp_path, monkeypatch, prefix):
    path = tmp_path / "app.apk"
    path.write_bytes(apk())
    monkeypatch.setattr(apktools, "tool", lambda name: name)

    def valid(command):
        if command[0] == "apksigner":
            return prefix + " certificate SHA-256 digest: " + "a" * 64
        return "package: name='com.beacon.mobile' versionCode='7' versionName='1.2.0'"

    monkeypatch.setattr(apktools, "output", valid)
    assert apktools.inspect(path)["version_code"] == 7
    monkeypatch.setattr(apktools, "output", lambda _: "package: name='other.app' versionCode='1' versionName='1.0'")
    with pytest.raises(HTTPException):
        apktools.inspect(path)
    path.write_bytes(b"not a zip")
    with pytest.raises(HTTPException):
        apktools.inspect(path)


def test_android_tool_failures_are_not_accepted(monkeypatch):
    monkeypatch.setattr(apktools.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1, "", "unsigned"))
    with pytest.raises(HTTPException):
        apktools.output(["apksigner", "verify", "bad.apk"])


@pytest.mark.parametrize("segmented", [False, True])
def test_built_release_apk_stream_upload_publish_and_download(client, db, monkeypatch, tmp_path, segmented):
    """Opt-in local integration: real Android tools and real bytes, isolated test DB/data only."""
    import hashlib
    import os
    from pathlib import Path

    value = os.environ.get("BEACON_TEST_APK")
    if not value:
        pytest.skip("Set BEACON_TEST_APK for the real built APK integration")
    path = Path(value)
    login(client, db)
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    if segmented:
        from app.modules.mobile import apk_uploads

        base = start(client, path.stat().st_size)
        with path.open("rb") as stream:
            offset = 0
            for chunk in iter(lambda: stream.read(apk_uploads.CHUNK_BYTES), b""):
                part = client.put(base + f"/chunks?offset={offset}", content=chunk)
                assert part.status_code == 200, part.text
                offset += len(chunk)
                assert part.json()["received"] == offset
        response = client.post(base + "/finish")
    else:
        with path.open("rb") as stream:
            response = client.post(
                "/api/mobile/app/uploads",
                content=iter(lambda: stream.read(1024**2), b""),
                headers={"Content-Type": "application/vnd.android.package-archive"},
            )
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["package"] == "com.beacon.mobile"
    assert client.get("/api/mobile/app").json()["current"] is None
    assert publish(client, item).status_code == 200
    link = client.post("/api/mobile/app/download-link").json()["path"]
    client.cookies.clear()
    downloaded = client.get(link)
    assert downloaded.status_code == 200
    assert len(downloaded.content) == path.stat().st_size == item["size"]
    assert hashlib.sha256(downloaded.content).hexdigest() == item["sha256"]


def start(client, size):
    response = client.post("/api/mobile/app/uploads/start", json={"size": size})
    assert response.status_code == 201, response.text
    return "/api/mobile/app/uploads/" + response.json()["upload_id"]


def test_segmented_upload_retries_and_finishes_only_complete_file(client, db, setup_release):
    import hashlib

    data = apk()
    base = start(client, len(data))
    assert client.post(base + "/finish").status_code == 409
    assert client.put(base + "/chunks?offset=1", content=data[:10]).status_code == 409
    first = client.put(base + "/chunks?offset=0", content=data[:10])
    assert first.json()["received"] == 10
    assert client.put(base + "/chunks?offset=0", content=data[:10]).json()["received"] == 10
    assert client.put(base + "/chunks?offset=0", content=b"different!").status_code == 409
    assert client.put(base + "/chunks?offset=10", content=data[10:]).json()["received"] == len(data)
    result = client.post(base + "/finish")
    assert result.status_code == 201, result.text
    assert result.json()["sha256"] == hashlib.sha256(data).hexdigest()
    assert client.get("/api/mobile/app").json()["current"] is None
    assert client.post(base + "/finish").status_code == 404
    assert not list((releases.directory() / "staging").iterdir())


def test_segmented_upload_permissions_limits_and_cleanup(client, db, setup_release):
    from app.modules.mobile import apk_uploads

    base = start(client, 100)
    assert client.put(base + "/chunks?offset=0", content=b"x" * 101).status_code == 422
    assert client.put(base + "/chunks?offset=0", content=b"x" * (apk_uploads.CHUNK_BYTES + 1)).status_code == 413
    assert client.post("/api/mobile/app/uploads/start", json={"size": releases.MAX_BYTES + 1}).status_code == 422
    other = make_operator(db, username="other-admin")
    stranger = session(other)
    assert stranger.put(base + "/chunks?offset=0", content=b"x").status_code == 404
    assert stranger.post(base + "/finish").status_code == 404
    assert stranger.delete(base).status_code == 404
    user = make_operator(db, username="upload-member")
    user.role = "member"
    db.commit()
    member = session(user)
    assert member.post("/api/mobile/app/uploads/start", json={"size": 100}).status_code == 403
    assert member.put(base + "/chunks?offset=0", content=b"x").status_code == 403
    assert member.post(base + "/finish").status_code == 403
    assert member.delete(base).status_code == 403
    assert client.delete(base).status_code == 204
    assert client.put(base + "/chunks?offset=0", content=b"x").status_code == 404


def test_segmented_upload_expiry_and_active_limit(client, db, setup_release, monkeypatch):
    from app.modules.mobile import apk_uploads

    bases = [start(client, 100) for _ in range(4)]
    assert client.post("/api/mobile/app/uploads/start", json={"size": 100}).status_code == 409
    future = time.time() + 7200
    monkeypatch.setattr(apk_uploads.time, "time", lambda: future)
    assert client.post(bases[0] + "/finish").status_code == 410
    assert start(client, 100)
    assert len(list((releases.directory() / "staging").iterdir())) == 1


def test_built_apk_through_real_next_http_proxy(client, db, monkeypatch, tmp_path):
    """Opt-in real HTTP: Next rewrite -> Uvicorn -> Android tools -> signed download."""
    import os
    import shutil
    import socket
    import threading
    from pathlib import Path

    import httpx
    import uvicorn

    if not os.environ.get("BEACON_TEST_APK"):
        pytest.skip("Set BEACON_TEST_APK for real HTTP proxy and Android validation")
    repo = Path(__file__).resolve().parents[3]
    fixture = tmp_path / "next"
    fixture.mkdir()
    shutil.copy(repo / "apps/web/next.config.ts", fixture)
    (fixture / "node_modules").symlink_to(repo / "apps/web/node_modules")
    (fixture / "package.json").write_text('{"private":true}')
    (fixture / "app").mkdir()
    (fixture / "app/page.js").write_text('export default function Page(){return "probe"}')
    (fixture / "app/layout.js").write_text(
        "export default function Layout({children}){return <html><body>{children}</body></html>}"
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        api_port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(client.app, lifespan="off", log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            web_port = reservation.getsockname()[1]
        env = {**os.environ, "BEACON_API_URL": f"http://127.0.0.1:{api_port}", "NEXT_TELEMETRY_DISABLED": "1"}
        with (fixture / "next.log").open("w+") as log:
            process = subprocess.Popen(
                ["node", str(repo / "apps/web/node_modules/next/dist/bin/next"), "dev", "--port", str(web_port)],
                cwd=fixture,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(300):
                    try:
                        with socket.create_connection(("127.0.0.1", web_port), timeout=0.2):
                            break
                    except OSError:
                        if process.poll() is not None:
                            raise RuntimeError("Next startup failed") from None
                        time.sleep(0.1)
                with httpx.Client(base_url=f"http://127.0.0.1:{web_port}", timeout=120) as proxy:
                    test_built_release_apk_stream_upload_publish_and_download(proxy, db, monkeypatch, tmp_path, True)
            except Exception:
                log.seek(0)
                print(log.read()[-4000:])
                raise
            finally:
                process.terminate()
                process.wait(timeout=15)
                server.should_exit = True
                thread.join(timeout=10)
