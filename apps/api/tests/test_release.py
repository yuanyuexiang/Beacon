from fastapi import Response

from app.core.auth import set_session_cookie
from app.core.config import get_settings


def test_https_deployment_sets_secure_cookie(monkeypatch):
    monkeypatch.setenv("BEACON_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    try:
        response = Response()
        set_session_cookie(response, "qa-session")
        cookie = response.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    finally:
        get_settings.cache_clear()


def test_release_health_is_actual_runtime_commit(client, monkeypatch):
    monkeypatch.setenv("BEACON_RELEASE_SHA", "a" * 40)
    get_settings.cache_clear()
    try:
        assert client.get("/api/health").json() == {"status": "ok", "release": "a" * 40}
    finally:
        get_settings.cache_clear()
