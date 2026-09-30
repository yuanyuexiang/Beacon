"""D2：未认证不可读取记录或下载文件；登录/登出；引导首个操作者只创建一次；路径穿越被拒。"""

from pathlib import Path

from sqlalchemy import select

from app.core.auth import bootstrap_operator, hash_password, verify_password
from app.core.models import Operator


def make_operator(db, username="tester", password="pw-tester-123"):
    op = Operator(username=username, password_hash=hash_password(password), is_active=True)
    db.add(op)
    db.commit()
    return op


def test_password_hash_roundtrip():
    h = hash_password("secret-1")
    assert verify_password("secret-1", h) and not verify_password("secret-2", h)


def test_me_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401


def test_login_wrong_password(client, db):
    make_operator(db)
    r = client.post("/api/auth/login", json={"username": "tester", "password": "wrong"})
    assert r.status_code == 401


def test_login_and_logout(client, db):
    make_operator(db)
    r = client.post("/api/auth/login", json={"username": "tester", "password": "pw-tester-123"})
    assert r.status_code == 200 and r.json()["username"] == "tester"
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_cookie_rejected(client, db):
    make_operator(db)
    client.post("/api/auth/login", json={"username": "tester", "password": "pw-tester-123"})
    client.cookies.set("beacon_session", client.cookies.get("beacon_session")[:-4] + "0000")
    assert client.get("/api/auth/me").status_code == 401


def test_bootstrap_operator_once(db, monkeypatch):
    from app.core import config as cfg

    monkeypatch.setenv("BEACON_BOOTSTRAP_OPERATOR", "admin")
    monkeypatch.setenv("BEACON_BOOTSTRAP_PASSWORD", "admin-pass-123456")
    cfg.get_settings.cache_clear()
    assert bootstrap_operator(db) is not None
    assert bootstrap_operator(db) is None  # 已有操作者则不再创建
    assert len(db.scalars(select(Operator)).all()) == 1
    cfg.get_settings.cache_clear()


def test_file_access_requires_login_and_stays_in_data_dir(client, db):
    from app.core.files import data_dir

    f = Path(data_dir()) / "evidence" / "x" / "menu.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("hello")
    assert client.get("/api/files/evidence/x/menu.txt").status_code == 401
    make_operator(db)
    client.post("/api/auth/login", json={"username": "tester", "password": "pw-tester-123"})
    assert client.get("/api/files/evidence/x/menu.txt").text == "hello"
    assert client.get("/api/files/evidence/x/nope.txt").status_code == 404
    r = client.get("/api/files/../../etc/passwd")
    assert r.status_code in (400, 404)
    r = client.get("/api/files/evidence/%2e%2e/%2e%2e/%2e%2e/etc/passwd")
    assert r.status_code in (400, 404)
