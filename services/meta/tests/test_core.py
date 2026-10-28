import hashlib
import hmac
import json
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from meta_service.core import Core, MetaError
from meta_service.server import app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    c = Core(tmp_path)
    c.configure_app(
        {
            "app_id": "123",
            "app_secret": "private-app-secret",
            "verify_token": "test-verify-token-123",
            "redirect_uri": "http://localhost:3000/api/outreach/oauth/callback",
            "version": "v25.0",
        }
    )
    key = str(uuid.uuid4())
    c.configure_account(
        key, {"platform": "facebook", "auth_mode": "facebook_login", "sender_id": "1234", "token": "private-page-token"}
    )
    calls = []

    def graph(a, method, path, body=None):
        calls.append((method, path, body, a["token"]))
        return {"id": "1234", "name": "Our page"} if method == "GET" else {"message_id": "m.1"}

    monkeypatch.setattr(c, "graph", graph)
    c.check(key)
    return c, key, calls


def preview(c, key):
    return c.preview(
        {
            "account_id": key,
            "recipient_id": "999",
            "window_expires_at": int(time.time()) + 86400,
            "text": "Approved reply",
            "request_key": uuid.uuid4().hex,
        }
    )


def test_single_send_and_ledger_replay(setup):
    c, key, calls = setup
    p = preview(c, key)
    assert not c.account_status(key)["sending_enabled"]
    with pytest.raises(MetaError):
        c.send(p["approval_token"])
    c.policy(key, True)
    assert c.send(p["approval_token"])["status"] == "sent"
    assert c.send(p["approval_token"])["message_id"] == "m.1"
    assert sum(method == "POST" for method, *_ in calls) == 1
    assert calls[-1][2]["messaging_type"] == "RESPONSE"
    assert "private-page-token" not in json.dumps(c.account_status(key))


def test_timeout_unknown_never_reposts(setup, monkeypatch):
    c, key, _ = setup
    c.policy(key, True)
    count = []

    def uncertain(*args):
        count.append(1)
        raise MetaError("平台连接失败；发送结果需对账确认")

    monkeypatch.setattr(c, "graph", uncertain)
    p = preview(c, key)
    assert c.send(p["approval_token"])["status"] == "unknown"
    assert c.send(p["approval_token"])["status"] == "unknown"
    assert c.request_status(p["request_key"])["status"] == "unknown"
    assert len(count) == 1


def test_reconfigure_disconnect_and_identity_mismatch(setup, monkeypatch):
    c, key, _ = setup
    p = preview(c, key)
    c.disconnect(key)
    with pytest.raises(MetaError):
        c.send(p["approval_token"])
    c.configure_account(
        key, {"platform": "facebook", "auth_mode": "facebook_login", "sender_id": "1234", "token": "new"}
    )
    monkeypatch.setattr(c, "graph", lambda *_: {"id": "other-page"})
    with pytest.raises(MetaError, match="不一致"):
        c.check(key)
    assert not c.account_status(key)["verified"]


def test_instagram_host_and_send_shape(tmp_path, monkeypatch):
    c = Core(tmp_path)
    key = str(uuid.uuid4())
    c.configure_account(
        key, {"platform": "instagram", "auth_mode": "instagram_login", "sender_id": "5678", "token": "ig-token"}
    )
    requests = []

    def request(_, method, url, **kwargs):
        requests.append((method, url, kwargs))
        body = {"user_id": "5678", "username": "our_business"} if method == "GET" else {"message_id": "ig.1"}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx.Client, "request", request)
    c.check(key)
    c.policy(key, True)
    assert c.send(preview(c, key)["approval_token"])["status"] == "sent"
    assert requests[-1][1] == "https://graph.instagram.com/v25.0/5678/messages"
    assert "messaging_type" not in requests[-1][2]["json"]
    assert requests[-1][2]["headers"]["Authorization"] == "Bearer ig-token"


def test_signed_webhook_rejects_tampering_echo_future(setup):
    c, _, _ = setup
    event = {
        "sender": {"id": "999"},
        "recipient": {"id": "1234"},
        "timestamp": int(time.time() * 1000),
        "message": {"mid": "m.inbound", "text": "hello"},
    }
    data = {"object": "page", "entry": [{"id": "1234", "messaging": [event]}]}
    raw = json.dumps(data).encode()
    signature = "sha256=" + hmac.new(b"private-app-secret", raw, hashlib.sha256).hexdigest()
    assert c.webhook(raw, signature)[0]["recipient_id"] == "999"
    with pytest.raises(MetaError):
        c.webhook(raw + b" ", signature)
    event["message"]["is_echo"] = True
    raw = json.dumps(data).encode()
    signature = "sha256=" + hmac.new(b"private-app-secret", raw, hashlib.sha256).hexdigest()
    assert c.webhook(raw, signature) == []
    assert c.webhook_challenge("test-verify-token-123", "challenge") == "challenge"


def test_http_auth_and_invalid_input_never_echo_credentials(tmp_path, monkeypatch):
    token = tmp_path / "service-key"
    token.write_text("service-secret")
    monkeypatch.setenv("META_SERVICE_TOKEN_FILE", str(token))
    monkeypatch.setenv("META_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/app").status_code == 401
        result = client.put(
            "/app", headers={"Authorization": "Bearer service-secret"}, json={"app_secret": "do-not-echo"}
        )
        assert result.status_code == 422 and "do-not-echo" not in result.text
        assert client.get("/accounts/app", headers={"Authorization": "Bearer service-secret"}).status_code == 422


def test_oauth_state_expires_and_is_single_use(setup):
    c, key, _ = setup
    data = {"platform": "facebook", "auth_mode": "facebook_login", "sender_id": "1234"}
    result = c.oauth_start(key, data, "b" * 64)
    assert "www.facebook.com/v25.0/dialog/oauth" in result["url"]
    with c.db() as db:
        state = db.execute("SELECT key FROM states").fetchone()[0]
        db.execute("UPDATE states SET expires=0")
    with pytest.raises(MetaError, match="过期"):
        c.oauth_finish(state, "code", "b" * 64)
    with pytest.raises(MetaError, match="使用"):
        c.oauth_finish(state, "code", "b" * 64)


def test_service_limits_count_each_request_and_manual_unknown_resolution(setup, monkeypatch):
    c, key, calls = setup
    c.policy(key, True, daily_limit=1)
    first = preview(c, key)
    c.send(first["approval_token"])
    with pytest.raises(MetaError, match="限额"):
        c.send(preview(c, key)["approval_token"])
    assert sum(method == "POST" for method, *_ in calls) == 1
    with pytest.raises(MetaError, match="不能人工覆盖"):
        c.manual_reconcile(first["request_key"], {"status": "failed", "reason": "checked no submission"})


def test_preview_cannot_outlive_conversation_window(setup):
    c, key, _ = setup
    with pytest.raises(MetaError, match="过期"):
        c.preview(
            {
                "account_id": key,
                "recipient_id": "999",
                "text": "reply",
                "request_key": uuid.uuid4().hex,
                "window_expires_at": int(time.time()) - 1,
            }
        )


def test_http_webhook_signature_parser(tmp_path, monkeypatch):
    import base64

    token = tmp_path / "internal"
    token.write_text("test-internal-key")
    data_dir = tmp_path / "data"
    monkeypatch.setenv("META_SERVICE_TOKEN_FILE", str(token))
    monkeypatch.setenv("META_DATA_DIR", str(data_dir))
    c = Core(data_dir)
    c.configure_app(
        {
            "app_id": "123",
            "app_secret": "test-app-secret",
            "verify_token": "test-verify-token-123",
            "redirect_uri": "http://localhost:3000/api/outreach/oauth/callback",
            "version": "v25.0",
        }
    )
    raw = json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": "1234",
                    "messaging": [
                        {
                            "sender": {"id": "999"},
                            "recipient": {"id": "1234"},
                            "timestamp": int(time.time() * 1000),
                            "message": {"mid": "m.123", "text": "hello"},
                        }
                    ],
                }
            ],
        }
    ).encode()
    signature = "sha256=" + hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        response = client.post(
            "/webhook/verify",
            headers={"Authorization": "Bearer test-internal-key"},
            json={"raw": base64.b64encode(raw).decode(), "signature": signature},
        )
        assert response.status_code == 200
        assert response.json()["events"][0]["message_id"] == "m.123"


def test_manual_unknown_resolution_is_durable_and_never_resends(setup, monkeypatch):
    c, key, calls = setup
    c.policy(key, True)

    def uncertain(*_):
        raise MetaError("平台连接失败")

    monkeypatch.setattr(c, "graph", uncertain)
    p = preview(c, key)
    assert c.send(p["approval_token"])["status"] == "unknown"
    verified = {
        "status": "sent",
        "message_id": "verified.id",
        "sent_at": time.time() - 10,
        "reason": "Operator inspected exact platform message",
        "confirmed": True,
    }
    assert c.manual_reconcile(p["request_key"], verified)["message_id"] == "verified.id"
    assert c.send(p["approval_token"])["message_id"] == "verified.id"


@pytest.mark.parametrize("failure", ["exchange", "identity", "success"])
def test_oauth_candidate_preserves_live_connection(setup, monkeypatch, failure):
    c, key, _ = setup
    c.policy(key, True, 37)
    old = c.read(key)
    data = {"platform": "facebook", "auth_mode": "facebook_login", "sender_id": "1234"}
    c.oauth_start(key, data, "b" * 64)
    assert c.read(key) == old
    with c.db() as db:
        state = db.execute("SELECT key FROM states").fetchone()[0]
    with pytest.raises(MetaError, match="会话不匹配"):
        c.oauth_finish(state, "code", "x" * 64)
    assert c.read(key) == old
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda *a, **kw: httpx.Response(400 if failure == "exchange" else 200, json={"access_token": "candidate-user"}),
    )
    monkeypatch.setattr(
        c,
        "graph",
        lambda a, method, path: (
            {"access_token": "candidate-page"}
            if "access_token" in path
            else {"id": "wrong" if failure == "identity" else "1234", "name": "Page"}
        ),
    )
    if failure == "success":
        c.oauth_finish(state, "code", "b" * 64)
        assert c.read(key)["token"] == "candidate-page"
        assert c.read(key)["daily_limit"] == 37
        assert c.read(key)["verified"] and not c.read(key)["sending_enabled"]
        assert c.read(key)["version"] != old["version"]
    else:
        with pytest.raises(MetaError):
            c.oauth_finish(state, "code", "b" * 64)
        assert c.read(key) == old
    with pytest.raises(MetaError, match="使用"):
        c.oauth_finish(state, "code", "b" * 64)


def test_disconnect_invalidates_pending_oauth(setup):
    c, key, _ = setup
    c.oauth_start(key, {"platform": "facebook", "auth_mode": "facebook_login", "sender_id": "1234"}, "b" * 64)
    with c.db() as db:
        state = db.execute("SELECT key FROM states").fetchone()[0]
    c.disconnect(key)
    with pytest.raises(MetaError, match="账号已变化"):
        c.oauth_finish(state, "code", "b" * 64)
    assert not c.read(key)["token"]


@pytest.mark.parametrize("code,status", [(190, 400), (200, 403), (100, 400)])
def test_graph_diagnostics_redact_upstream_credentials(tmp_path, monkeypatch, code, status):
    c = Core(tmp_path)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            json={
                "error": {"code": code, "error_subcode": 42, "message": "secret-page-token secret-app-key"},
            },
        )
    )
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=transport, **kw))
    with pytest.raises(MetaError) as caught:
        c.graph({"token": "secret-page-token"}, "GET", "me?fields=id,name")
    text = str(caught.value)
    assert f"code={code}" in text and "error_subcode=42" in text
    assert "secret-page-token" not in text and "secret-app-key" not in text


def test_page_identity_permission_error_is_actionable_and_redacted(tmp_path, monkeypatch):
    c = Core(tmp_path)
    original = httpx.Client
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            400,
            json={
                "error": {
                    "code": 100,
                    "message": "This endpoint requires the 'pages_read_engagement' permission. secret-page-token",
                }
            },
        )
    )
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=transport, **kw))
    with pytest.raises(MetaError) as caught:
        c.graph({"token": "secret-page-token"}, "GET", "me?fields=id,name")
    assert "pages_read_engagement" in str(caught.value)
    assert "重新授权" in str(caught.value)
    assert "secret-page-token" not in str(caught.value)


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_page_login_requests_identity_permission(setup, platform):
    from urllib.parse import parse_qs, urlsplit

    c, key, _ = setup
    account = {"platform": platform, "auth_mode": "facebook_login", "sender_id": "1234", "page_id": "1234"}
    url = c.oauth_start(key, account, "b" * 64)["url"]
    scopes = parse_qs(urlsplit(url).query)["scope"][0].split(",")
    assert "pages_read_engagement" in scopes
    assert ("pages_messaging" if platform == "facebook" else "instagram_manage_messages") in scopes
