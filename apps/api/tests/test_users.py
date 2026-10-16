"""用户角色、首次改密、会话撤销和管理员并发保护；禁止真实外部调用。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.auth import COOKIE, make_session_token, verify_password
from app.core.models import AuditLog, Operator
from app.main import app
from tests.test_auth import make_operator
from tests.test_imports import login

INITIAL = "Start123"
NEW = "Next1234"


def create(client, username="sales", role="member"):
    r = client.post(
        "/api/users", json={"username": username, "display_name": "销售", "role": role, "initial_password": INITIAL}
    )
    assert r.status_code == 201, r.text
    return r.json()


def session(op):
    c = TestClient(app)
    c.cookies.set(COOKIE, make_session_token(str(op.id), op.session_version))
    return c


def test_create_first_password_gate_profile_and_no_secret_leak(client, db):
    login(client, db)
    row = create(client)
    assert "password" not in row and "password_hash" not in row
    assert row["must_change_password"] and row["role"] == "member"
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "sales", "password": INITIAL})
    assert r.status_code == 200 and r.json()["must_change_password"]
    for path in ("/api/batches", "/api/users", "/api/files/evidence/test"):
        denied = c.get(path)
        assert denied.status_code == 403
        assert denied.headers["X-Beacon-Action"] == "change-password"
    assert c.post("/api/auth/password", json={"current_password": "wrong", "new_password": NEW}).status_code == 400
    assert c.post("/api/auth/password", json={"current_password": INITIAL, "new_password": INITIAL}).status_code == 422
    assert c.post("/api/auth/password", json={"current_password": INITIAL, "new_password": NEW}).status_code == 200
    assert c.get("/api/batches").status_code == 200
    assert c.patch("/api/auth/profile", json={"display_name": " 新名字 "}).json()["display_name"] == "新名字"
    assert c.get("/api/auth/me").json()["username"] == "sales"
    payloads = str([(a.before, a.after) for a in db.scalars(select(AuditLog)).all()])
    assert INITIAL not in payloads and NEW not in payloads and "scrypt$" not in payloads
    invalid = client.post("/api/users", json={"username": "bad", "initial_password": "Short12"})
    assert invalid.status_code == 422 and "Short12" not in invalid.text


def test_unique_names_and_last_admin_protection(client, db):
    login(client, db)
    admin = db.scalar(select(Operator))
    assert client.patch(f"/api/users/{admin.id}", json={"role": "member"}).status_code == 409
    assert client.patch(f"/api/users/{admin.id}", json={"is_active": False}).status_code == 409
    assert client.patch(f"/api/users/{admin.id}", json={"role": None}).status_code == 422
    create(client, "duplicate")
    assert client.post("/api/users", json={"username": "DUPLICATE", "initial_password": INITIAL}).status_code == 409
    other = create(client, "other-admin", "admin")
    assert client.patch(f"/api/users/{other['id']}", json={"is_active": False}).status_code == 200
    assert client.patch(f"/api/users/{admin.id}", json={"is_active": False}).status_code == 409
    assert client.patch(f"/api/users/{other['id']}", json={"is_active": True}).status_code == 200
    assert client.patch(f"/api/users/{admin.id}", json={"role": "member"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/users").status_code == 401


@pytest.mark.parametrize("change", ["password", "reset", "disable", "role", "logout"])
def test_existing_sessions_revoked_and_disable_restore_does_not_resurrect(client, db, change):
    login(client, db)
    make_operator(db, "member", INITIAL)
    user = db.scalar(select(Operator).where(Operator.username == "member"))
    old = session(user)
    another = session(user)
    if change == "password":
        assert (
            another.post("/api/auth/password", json={"current_password": INITIAL, "new_password": NEW}).status_code
            == 200
        )
        assert another.get("/api/auth/me").status_code == 200
    elif change == "reset":
        assert client.post(f"/api/users/{user.id}/reset-password", json={"temporary_password": NEW}).status_code == 200
        assert another.post("/api/auth/login", json={"username": user.username, "password": INITIAL}).status_code == 401
        assert another.post("/api/auth/login", json={"username": user.username, "password": NEW}).json()[
            "must_change_password"
        ]
    elif change == "disable":
        assert client.patch(f"/api/users/{user.id}", json={"is_active": False}).status_code == 200
        assert another.post("/api/auth/login", json={"username": user.username, "password": INITIAL}).status_code == 401
        assert client.patch(f"/api/users/{user.id}", json={"is_active": True}).status_code == 200
    elif change == "role":
        assert client.patch(f"/api/users/{user.id}", json={"role": "viewer"}).status_code == 200
    else:
        assert another.post("/api/auth/logout").status_code == 204
    assert old.get("/api/auth/me").status_code == 401


ADMIN_WRITES = [
    ("POST", "/api/users"),
    ("PATCH", "/api/users/00000000-0000-0000-0000-000000000001"),
    ("POST", "/api/users/00000000-0000-0000-0000-000000000001/reset-password"),
    ("PUT", "/api/lead-policy"),
    ("POST", "/api/directory/regions"),
    ("PATCH", "/api/directory/regions/197"),
    ("POST", "/api/directory/authorities/refresh"),
    ("POST", "/api/directory/regions/197/sync"),
    ("POST", "/api/gmail/credentials"),
    ("POST", "/api/gmail/check"),
    ("POST", "/api/gmail/connect"),
    ("POST", "/api/gmail/disconnect"),
    ("PUT", "/api/gmail/policy"),
    ("PUT", "/api/outreach/app"),
    ("POST", "/api/outreach/accounts"),
    ("PUT", "/api/outreach/accounts/00000000-0000-0000-0000-000000000001/credentials"),
    ("POST", "/api/outreach/accounts/00000000-0000-0000-0000-000000000001/connect"),
]


@pytest.mark.parametrize("method,path", ADMIN_WRITES)
def test_member_cannot_configure_by_direct_api(client, db, method, path):
    op = make_operator(db)
    op.role = "member"
    db.commit()
    c = session(op)
    assert c.request(method, path, json={}).status_code == 403
    assert c.get("/api/users").status_code == 403


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/batches"),
        ("POST", "/api/lists"),
        ("POST", "/api/imports"),
        ("PATCH", "/api/leads/00000000-0000-0000-0000-000000000001"),
        ("POST", "/api/gmail/approve"),
        ("POST", "/api/outreach/approve"),
        ("POST", "/api/tasks/00000000-0000-0000-0000-000000000001/sent"),
    ],
)
def test_viewer_cannot_write_but_can_read(client, db, method, path):
    op = make_operator(db)
    op.role = "viewer"
    db.commit()
    c = session(op)
    assert c.request(method, path, json={}).status_code == 403
    assert c.get("/api/batches").status_code == 200
    assert c.get("/api/directory/regions").status_code == 200


def test_member_can_create_business_data_and_viewer_can_change_own_password(client, db):
    op = make_operator(db)
    op.role = "member"
    db.commit()
    c = session(op)
    assert (
        c.post("/api/batches", json={"batch_key": "member", "country": "GB", "source_name": "manual"}).status_code
        == 201
    )
    op.role = "viewer"
    db.commit()
    assert c.patch("/api/auth/profile", json={"role": "admin"}).status_code == 422
    assert c.patch("/api/auth/profile", json={"display_name": "只读用户"}).status_code == 200
    assert (
        c.post("/api/auth/password", json={"current_password": "pw-tester-123", "new_password": NEW}).status_code == 200
    )


def test_concurrent_admin_demotion_keeps_one_active_admin(client, db):
    one = make_operator(db, "first", INITIAL)
    two = make_operator(db, "second", INITIAL)
    clients = [session(one), session(two)]
    identities = [one.id, two.id]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(c.patch, f"/api/users/{uid}", json={"role": "member"})
            for c, uid in zip(clients, identities, strict=True)
        ]
        statuses = sorted(f.result().status_code for f in futures)
    assert statuses == [200, 409]
    db.expire_all()
    assert sum(u.role == "admin" and u.is_active for u in db.scalars(select(Operator)).all()) == 1


def test_profile_change_keeps_history_and_password(client, db):
    login(client, db)
    op = db.scalar(select(Operator))
    old_hash = op.password_hash
    assert client.patch(f"/api/users/{op.id}", json={"display_name": "管理员"}).status_code == 200
    db.refresh(op)
    assert op.password_hash == old_hash and verify_password("pw-tester-123", old_hash)
    assert client.delete(f"/api/users/{op.id}").status_code == 405
    assert client.get("/api/users").json()[0]["display_name"] == "管理员"


def test_upgrade_preserves_existing_admin_password_and_legacy_cookie(client, db):
    import base64
    import json
    import time

    from alembic import command

    from app.core.auth import _sign
    from tests.conftest import alembic_config

    op = make_operator(db)
    identity, previous_hash = op.id, op.password_hash
    command.downgrade(alembic_config(), "d157a0010001")
    command.upgrade(alembic_config(), "head")
    db.expire_all()
    restored = db.get(Operator, identity)
    assert restored.role == "admin" and restored.password_hash == previous_hash
    assert restored.session_version == 0 and not restored.must_change_password
    payload = json.dumps({"op": str(identity), "exp": int(time.time()) + 120}).encode()
    token = base64.urlsafe_b64encode(payload).decode() + "." + _sign(payload)
    c = TestClient(app)
    c.cookies.set(COOKIE, token)
    assert c.get("/api/auth/me").status_code == 200
