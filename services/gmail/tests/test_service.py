import json
import time

import pytest
from fastapi.testclient import TestClient

from gmail_service import core, oauth, server

SECRET = "test-service-token-0123456789abcdef"
AUTH = {"Authorization": "Bearer " + SECRET}
CREDENTIALS = {"installed": {"client_id": "qa", "client_secret": "test-private"}}
TOKEN = {"scope": " ".join(core.GMAIL_SCOPES), "refresh_token": "test-refresh"}
MAIL = {"to": ["customer@example.com"], "subject": "QA menu", "body": "Reviewed message"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for env, filename in [
        ("GMAIL_CREDENTIALS_PATH", "credentials.json"),
        ("GMAIL_TOKEN_PATH", "token.json"),
        ("GMAIL_APPROVAL_SECRET_PATH", "approval-secret"),
        ("GMAIL_AUDIT_DB", "audit.db"),
        ("GMAIL_SERVICE_TOKEN_FILE", "access-secret"),
    ]:
        monkeypatch.setenv(env, str(tmp_path / filename))
    (tmp_path / "access-secret").write_text(SECRET)
    # 任何遗漏的网络调用立即失败，测试从不发送真实邮件。
    monkeypatch.setattr(
        core.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden"))
    )
    monkeypatch.setattr(
        oauth,
        "validate_token",
        lambda config, token: (
            {**token, "access_token": "qa", "expires_in": 3600, "obtained_at": int(time.time())},
            "qa@example.com",
        ),
    )
    monkeypatch.setattr(oauth, "identity", lambda *a: {"email": "qa@example.com"})
    client = TestClient(server.app)
    yield client
    client.close()


def test_auth_import_scope_status_and_secret_not_returned(setup):
    assert setup.get("/auth/status").status_code == 401
    assert (
        setup.post("/auth/import", headers=AUTH, json={"credentials": CREDENTIALS, "token": TOKEN}).status_code == 200
    )
    result = setup.get("/auth/status", headers=AUTH)
    assert result.json()["send_authorized"] and result.json()["readonly_authorized"]
    assert "test-private" not in result.text and "test-refresh" not in result.text
    assert "token_path" not in result.text
    assert setup.post("/auth/start", headers=AUTH).status_code == 400
    assert setup.post("/auth/disconnect", headers=AUTH).json()["connected"] is False
    assert not core.token_path().exists()


def test_import_rejects_non_google_endpoints_and_missing_refresh(setup):
    assert (
        setup.post(
            "/auth/import",
            headers=AUTH,
            json={"credentials": {"web": {"client_id": "x", "client_secret": "y", "token_uri": "http://localhost"}}},
        ).status_code
        == 400
    )
    assert (
        setup.post(
            "/auth/import", headers=AUTH, json={"credentials": CREDENTIALS, "token": {"scope": "gmail"}}
        ).status_code
        == 400
    )


def test_default_paused_approval_binding_and_idempotency(setup, monkeypatch):
    token = setup.post("/preview", headers=AUTH, json=MAIL).json()["approval_token"]
    payload = {**MAIL, "approval_token": token, "request_key": "qa"}
    assert setup.post("/send", headers=AUTH, json=payload).status_code == 409
    setup.put("/policy", headers=AUTH, json={"sending_enabled": True})
    count = []

    def fake_send(mail, approval):
        count.append(mail)
        return {"status": "sent", "id": "abc", "threadId": "thread", "sent_at": int(time.time())}

    monkeypatch.setattr(core, "send_approved", fake_send)
    assert setup.post("/send", headers=AUTH, json=payload).json()["status"] == "sent"
    assert setup.post("/send", headers=AUTH, json=payload).json()["id"] == "abc"
    assert len(count) == 1
    assert setup.post("/send", headers=AUTH, json={**payload, "body": "changed"}).status_code == 502
    assert setup.get("/requests/qa", headers=AUTH).json()["status"] == "sent"


def test_unknown_attempt_not_retried_and_audit_recovery(setup, monkeypatch):
    setup.put("/policy", headers=AUTH, json={"sending_enabled": True})
    token = setup.post("/preview", headers=AUTH, json=MAIL).json()["approval_token"]
    count = []

    def interrupted(mail, approval):
        count.append(1)
        with core._audit_connect() as conn:
            conn.execute(
                "INSERT INTO sends(fingerprint,recipients,subject,status,created_at) VALUES(?,?,?,'unknown',?)",
                (core._fingerprint(mail), json.dumps(mail["to"]), mail["subject"], int(time.time())),
            )
        raise core.GmailError("unknown")

    monkeypatch.setattr(core, "send_approved", interrupted)
    payload = {**MAIL, "approval_token": token, "request_key": "qa-unknown"}
    assert setup.post("/send", headers=AUTH, json=payload).json()["status"] == "unknown"
    assert setup.post("/send", headers=AUTH, json=payload).json()["status"] == "unknown"
    assert len(count) == 1
    with core._audit_connect() as conn:
        conn.execute("UPDATE sends SET status='sent',gmail_message_id='recovered',gmail_thread_id='t'")
    assert setup.get("/requests/qa-unknown", headers=AUTH).json()["id"] == "recovered"


def test_web_oauth_state_single_use_and_connection_check(setup, monkeypatch):
    credentials = {
        "web": {**CREDENTIALS["installed"], "redirect_uris": ["http://localhost:3000/api/gmail/oauth/callback"]}
    }
    setup.post("/auth/import", headers=AUTH, json={"credentials": credentials})
    url = setup.post("/auth/start", headers=AUTH).json()["url"]
    from urllib.parse import parse_qs, urlsplit

    state = parse_qs(urlsplit(url).query)["state"][0]
    monkeypatch.setattr(core, "_post_form", lambda *a: {**TOKEN, "access_token": "fresh", "expires_in": 3600})
    monkeypatch.setattr(core, "_gmail_get", lambda *a: {"emailAddress": "qa@example.com"})
    result = setup.post("/auth/callback", headers=AUTH, json={"code": "qa-code", "state": state})
    assert result.json()["connected"]
    assert setup.post("/auth/callback", headers=AUTH, json={"code": "qa-code", "state": state}).status_code == 400
    assert setup.post("/auth/callback", headers=AUTH, json={"code": "qa-code", "state": "wrong"}).status_code == 400


def test_reauthorization_invalidates_old_approvals_and_pauses(setup, monkeypatch):
    old = setup.post("/preview", headers=AUTH, json=MAIL).json()["approval_token"]
    setup.put("/policy", headers=AUTH, json={"sending_enabled": True, "queue_enabled": True})
    setup.post("/auth/import", headers=AUTH, json={"credentials": CREDENTIALS, "token": TOKEN})
    policy = setup.get("/policy", headers=AUTH).json()
    assert not policy["sending_enabled"] and not policy["queue_enabled"]
    setup.put("/policy", headers=AUTH, json={"sending_enabled": True})
    assert (
        setup.post(
            "/send", headers=AUTH, json={**MAIL, "approval_token": old, "request_key": "old-account"}
        ).status_code
        == 502
    )


def test_invalid_grant_is_visible_without_leaking_google_response(setup, monkeypatch):
    def invalid(*args):
        raise core.GmailError("invalid_grant secret-test-value")

    monkeypatch.setattr(core, "_access_token", invalid)
    response = setup.post("/auth/check", headers=AUTH)
    assert response.status_code == 502 and "invalid_grant" in response.text
    assert "secret-test-value" not in response.text
    result = setup.get("/auth/status", headers=AUTH).json()
    assert result["requires_reauth"] and not result["connected"]


@pytest.mark.parametrize("operation", ["refresh", "read"])
def test_transport_disconnect_is_bounded_and_sanitized(setup, monkeypatch, operation):
    import http.client

    calls = []

    def disconnected(*args, **kwargs):
        calls.append(1)
        raise http.client.RemoteDisconnected("proxy closed")

    monkeypatch.setattr(core.urllib.request, "urlopen", disconnected)
    monkeypatch.setattr(core.time, "sleep", lambda _: None)
    if operation == "refresh":
        with pytest.raises(core.GmailError):
            core._post_form("https://oauth2.googleapis.com/token", {})
    else:
        monkeypatch.setattr(core, "_access_token", lambda *a: "test-access")
        with pytest.raises(core.GmailError):
            core._gmail_get("profile")
    assert len(calls) == 3


def test_readonly_budget_prevents_unbounded_network_operations(setup, monkeypatch):
    monkeypatch.setattr(core, "_access_token", lambda *a: "test-access")
    with core.request_budget(0), pytest.raises(core.GmailError, match="时间上限"):
        core._gmail_get("profile")
    assert core.request_timeout() == 30


def test_ambiguous_oauth_client_configuration_rejected(setup):
    configuration = {"web": CREDENTIALS["installed"], "installed": CREDENTIALS["installed"]}
    assert setup.post("/auth/import", headers=AUTH, json={"credentials": configuration}).status_code == 400


def test_fixed_test_mail_paused_idempotent_and_bound_to_recipient(setup, monkeypatch):
    client = setup
    monkeypatch.setattr(server, "verify_connection", lambda: {"email": "sender@example.com"})
    calls = []
    monkeypatch.setattr(
        core, "send_approved", lambda payload, token: calls.append(payload) or {"status": "sent", "id": "mock"}
    )
    preview = client.post("/test/preview", headers=AUTH, json={"to": ["me@example.com"]})
    assert preview.status_code == 200
    assert preview.json()["from_email"] == "sender@example.com"
    body = {"to": ["me@example.com"], "approval_token": preview.json()["approval_token"], "request_key": "test-one"}
    assert client.post("/test/send", headers=AUTH, json=body).json()["status"] == "sent"
    assert client.post("/test/send", headers=AUTH, json=body).json()["status"] == "sent"
    assert len(calls) == 1 and calls[0]["subject"] == server.TEST_SUBJECT
    assert server.policy()["sending_enabled"] is False
    changed = {**body, "to": ["other@example.com"]}
    assert client.post("/test/send", headers=AUTH, json=changed).status_code >= 400


def test_send_rejection_reason_retained_and_private_response_omitted(setup, monkeypatch):
    import io
    import urllib.error

    monkeypatch.setattr(core, "_access_token", lambda *a: "mock")

    def rejected(*a, **k):
        payload = b'{"error":{"message":"private details","details":[{"reason":"SERVICE_DISABLED"}]}}'
        raise urllib.error.HTTPError("https://gmail.googleapis.com", 403, "Forbidden", {}, io.BytesIO(payload))

    monkeypatch.setattr(core.urllib.request, "urlopen", rejected)
    preview = core.preview(server.test_mail(["self@example.com"]))
    body = {"to": ["self@example.com"], "approval_token": preview["approval_token"], "request_key": "rejected"}
    result = setup.post("/test/send", headers=AUTH, json=body).json()
    assert result["status"] == "failed"
    assert "HTTP 403" in result["reason"] and "启用 Gmail API" in result["reason"]
    assert "private" not in str(result)
    assert setup.post("/test/send", headers=AUTH, json=body).json() == result
