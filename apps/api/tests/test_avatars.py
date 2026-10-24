import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from tests.test_imports import login
from tests.test_users import create


def picture():
    out = io.BytesIO()
    Image.new("RGB", (600, 400), "red").save(out, "PNG")
    return out.getvalue()


def test_avatar_roundtrip_replacement_removal(client, db):
    login(client, db)
    before = client.get("/api/auth/me").json()
    assert before["avatar_url"] is None
    r = client.put("/api/auth/avatar", files={"file": ("avatar.png", picture(), "image/png")})
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    image = client.get(url)
    assert image.status_code == 200
    assert Image.open(io.BytesIO(image.content)).size == (256, 256)
    assert image.headers["content-type"] == "image/jpeg"
    assert "no-store" in image.headers["cache-control"]
    assert TestClient(app).get(url).status_code == 401
    assert client.get("/api/users").json()[0]["avatar_url"] == url
    second = client.put("/api/auth/avatar", files={"file": ("new.png", picture())})
    assert second.json()["avatar_url"] != url
    assert client.delete("/api/auth/avatar").json()["avatar_url"] is None
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("content,status", [(b"<svg/>", 422), (b"x" * (5 * 1024 * 1024 + 1), 413)])
def test_invalid_upload_keeps_avatar(client, db, content, status):
    login(client, db)
    url = client.put("/api/auth/avatar", files={"file": ("a.png", picture())}).json()["avatar_url"]
    assert client.put("/api/auth/avatar", files={"file": ("a.png", content)}).status_code == status
    assert client.get("/api/auth/me").json()["avatar_url"] == url


def test_viewer_owns_avatar_and_first_password_gate(client, db):
    login(client, db)
    admin = client.get("/api/auth/me").json()
    create(client, "reader", "viewer")
    other = TestClient(app)
    other.post("/api/auth/login", json={"username": "reader", "password": "Start123"})
    assert other.put("/api/auth/avatar", files={"file": ("a.png", picture())}).status_code == 403
    other.post("/api/auth/password", json={"current_password": "Start123", "new_password": "Next1234"})
    result = other.put("/api/auth/avatar", files={"file": ("a.png", picture())})
    assert result.status_code == 200, result.text
    assert other.get(result.json()["avatar_url"]).status_code == 200
    assert client.get("/api/auth/me").json()["avatar_url"] == admin["avatar_url"]
    assert other.delete("/api/auth/avatar").status_code == 200
