"""Browser/session binding and sanitized OAuth callback. No Google traffic."""

from app.modules.gmail import client as gmail_client
from tests.test_imports import login


def test_web_connect_and_callback_bound_to_current_login(client, db, monkeypatch):
    login(client, db)
    calls = []

    def call(method, path, body=None):
        calls.append((path, body))
        if path == "/auth/start":
            return {"url": "https://accounts.google.com/authorization-test"}
        assert path == "/auth/callback"
        assert body["binding"] == calls[0][1]["binding"]
        return {"connected": True}

    monkeypatch.setattr(gmail_client, "call", call)
    response = client.post("/api/gmail/connect", json={"purpose": "replies"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=lax" in response.headers["set-cookie"]
    assert calls[0][1]["purpose"] == "replies"
    assert len(calls[0][1]["binding"]) == 64
    response = client.get("/api/gmail/oauth/callback?state=mock&code=private-code", follow_redirects=False)
    assert response.headers["location"] == "/settings?gmail=connected"
    assert "private-code" not in response.text and "no-store" in response.headers["cache-control"]
    assert "beacon_gmail_oauth" not in client.cookies


def test_callback_requires_logged_in_admin_browser(client, db, monkeypatch):
    login(client, db)
    calls = []
    monkeypatch.setattr(gmail_client, "call", lambda *args: calls.append(args))
    response = client.get("/api/gmail/oauth/callback?state=x&code=y", follow_redirects=False)
    assert "gmail=failed" in response.headers["location"] and not calls


def test_oauth_failure_is_actionable_and_sanitized(client, db, monkeypatch):
    login(client, db)

    def call(method, path, body=None):
        if path == "/auth/start":
            return {"url": "https://accounts.google.com/authorization-test"}
        raise gmail_client.GmailServiceError("invalid_grant: private-do-not-return")

    monkeypatch.setattr(gmail_client, "call", call)
    client.post("/api/gmail/connect", json={})
    response = client.get("/api/gmail/oauth/callback?state=x&code=y", follow_redirects=False)
    assert response.headers["location"] == "/settings?gmail=failed&gmail_error=invalid_grant"
    assert "private-do-not-return" not in response.text


def test_settings_test_mail_forwarded_without_creating_customer_task(client, db, monkeypatch):
    login(client, db)
    calls = []

    def fake_call(method, path, body):
        calls.append((path, body))
        return {"status": "sent"}

    monkeypatch.setattr(gmail_client, "call", fake_call)
    body = {"to": ["self@example.com"]}
    assert client.post("/api/gmail/test/preview", json=body).status_code == 200
    assert (
        client.post("/api/gmail/test/send", json={**body, "approval_token": "mock", "request_key": "one"}).status_code
        == 200
    )
    assert [path for path, _ in calls] == ["/test/preview", "/test/send"]
    assert (
        client.post("/api/gmail/test/preview", json={"to": ["one@example.com", "two@example.com"]}).status_code == 422
    )
