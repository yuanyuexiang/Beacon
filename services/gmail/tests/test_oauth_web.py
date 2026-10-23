"""No Google traffic; verify candidate account replacement and browser-bound OAuth."""

from urllib.parse import parse_qs, urlsplit

import pytest
from test_service import AUTH, CREDENTIALS, TOKEN
from test_service import setup as service_setup

from gmail_service import core, oauth, server


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from service_setup.__wrapped__(tmp_path, monkeypatch)


REDIRECT = "http://localhost:3000/api/gmail/oauth/callback"
WEB = {"web": {**CREDENTIALS["installed"], "redirect_uris": [REDIRECT]}}


def start(client, purpose="send", binding="browser-a"):
    assert client.post("/auth/configure", headers=AUTH, json={"credentials": WEB}).status_code == 200
    response = client.post("/auth/start", headers=AUTH, json={"binding": binding, "purpose": purpose})
    assert response.status_code == 200, response.text
    return parse_qs(urlsplit(response.json()["url"]).query)


def test_configuration_preserves_active_connection_and_uses_server_redirect(setup):
    setup.post("/auth/import", headers=AUTH, json={"credentials": CREDENTIALS, "token": TOKEN})
    before = core.token_path().read_bytes()
    setup.put("/policy", headers=AUTH, json={"sending_enabled": True})
    query = start(setup)
    assert core.token_path().read_bytes() == before
    assert setup.get("/policy", headers=AUTH).json()["sending_enabled"]
    assert core.GMAIL_METADATA_SCOPE not in query["scope"][0]
    assert core.GMAIL_SEND_SCOPE in query["scope"][0]
    assert query["code_challenge_method"] == ["S256"]
    stale = {"web": {**CREDENTIALS["installed"], "redirect_uris": ["https://wrong.example/callback"]}}
    assert setup.post("/auth/configure", headers=AUTH, json={"credentials": stale}).status_code == 200
    result = setup.post("/auth/start", headers=AUTH, json={"binding": "qa"})
    assert result.status_code == 200
    assert parse_qs(urlsplit(result.json()["url"]).query)["redirect_uri"] == [REDIRECT]
    assert core.token_path().read_bytes() == before


@pytest.mark.parametrize("error", ["invalid_grant", "access_denied", "missing_send_scope"])
def test_failed_reconnect_preserves_account_and_policy(setup, monkeypatch, error):
    setup.post("/auth/import", headers=AUTH, json={"credentials": CREDENTIALS, "token": TOKEN})
    before = core.token_path().read_bytes(), core.credentials_path().read_bytes()
    setup.put("/policy", headers=AUTH, json={"sending_enabled": True})
    query = start(setup)

    def fail(*a):
        raise core.GmailError(error + " PRIVATE-RESPONSE")

    monkeypatch.setattr(core, "_post_form", fail)
    response = setup.post(
        "/auth/callback", headers=AUTH, json={"state": query["state"][0], "binding": "browser-a", "code": "x"}
    )
    assert response.status_code == 502 and "PRIVATE-RESPONSE" not in response.text
    assert before == (core.token_path().read_bytes(), core.credentials_path().read_bytes())
    assert setup.get("/policy", headers=AUTH).json()["sending_enabled"]


def test_binding_single_use_pkce_and_success_pauses(setup, monkeypatch):
    query = start(setup)
    state = query["state"][0]
    wrong = {"state": state, "binding": "another-browser", "code": "x"}
    assert setup.post("/auth/callback", headers=AUTH, json=wrong).status_code == 400
    scopes = core.GMAIL_SEND_SCOPE + " openid email"

    def exchange(url, values):
        import base64
        import hashlib

        assert values["redirect_uri"] == REDIRECT and len(values["code_verifier"]) >= 43
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(values["code_verifier"].encode()).digest()).decode().rstrip("=")
        )
        assert query["code_challenge"] == [challenge]
        return {**TOKEN, "scope": scopes}

    monkeypatch.setattr(core, "_post_form", exchange)
    response = setup.post("/auth/callback", headers=AUTH, json={**wrong, "binding": "browser-a"})
    assert response.status_code == 200, response.text
    assert response.json()["connected"] and not response.json()["readonly_authorized"]
    assert not setup.get("/policy", headers=AUTH).json()["sending_enabled"]
    assert setup.post("/auth/callback", headers=AUTH, json={**wrong, "binding": "browser-a"}).status_code == 400


def test_expired_session_and_denial_never_replace(setup):
    query = start(setup, purpose="replies")
    assert core.GMAIL_METADATA_SCOPE in query["scope"][0]
    assert core.GMAIL_READONLY_SCOPE not in query["scope"][0]
    with server.db() as conn:
        conn.execute("UPDATE oauth_sessions_v2 SET expires=0")
    assert (
        setup.post(
            "/auth/callback",
            headers=AUTH,
            json={"state": query["state"][0], "binding": "browser-a", "error": "access_denied"},
        ).status_code
        == 400
    )
    assert not core.token_path().exists()


def test_send_only_connection_checks_identity_without_read_permission(setup, monkeypatch):
    token = {**TOKEN, "scope": core.GMAIL_SEND_SCOPE + " openid email"}
    setup.post("/auth/import", headers=AUTH, json={"credentials": CREDENTIALS, "token": token})
    monkeypatch.setattr(core, "_gmail_get", lambda *a: pytest.fail("send-only must not read inbox"))
    assert setup.post("/auth/check", headers=AUTH).status_code == 200


def test_candidate_validation_uses_supplied_client_and_never_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    captured = []
    monkeypatch.setattr(core, "_post_form", lambda url, values: captured.append(values) or {"access_token": "x"})
    monkeypatch.setattr(oauth, "identity", lambda *a: {"email": "qa@example.com"})
    candidate, email = oauth.validate_token(CREDENTIALS["installed"], TOKEN)
    assert captured[0]["client_id"] == "qa" and email == "qa@example.com"
    assert candidate["access_token"] == "x" and not core.token_path().exists()


def test_storage_failure_restores_previous_connection(setup, monkeypatch):
    setup.post("/auth/import", headers=AUTH, json={"credentials": CREDENTIALS, "token": TOKEN})
    old = core.credentials_path().read_bytes(), core.token_path().read_bytes(), core.secret_path().read_bytes()
    original = core._private_write
    failed = []

    def write(path, value):
        if path == core.token_path() and not failed:
            failed.append(True)
            raise OSError("simulated storage failure")
        return original(path, value)

    monkeypatch.setattr(core, "_private_write", write)
    response = setup.post("/auth/import", headers=AUTH, json={"credentials": WEB, "token": TOKEN})
    assert response.status_code == 503
    assert old == (
        core.credentials_path().read_bytes(),
        core.token_path().read_bytes(),
        core.secret_path().read_bytes(),
    )


def test_identity_prefers_openid_even_with_previous_gmail_read_grant(monkeypatch):
    import io
    import json

    urls = []

    def open_url(request, **kwargs):
        urls.append(request.full_url)
        return io.BytesIO(json.dumps({"email": "qa@example.com", "email_verified": True}).encode())

    monkeypatch.setattr(oauth.urllib.request, "urlopen", open_url)
    assert oauth.identity("mock", {"openid", "email", core.GMAIL_READONLY_SCOPE})["email"] == "qa@example.com"
    assert urls == ["https://openidconnect.googleapis.com/v1/userinfo"]


@pytest.mark.parametrize("code", [401, 403])
def test_identity_http_error_is_actionable_without_leaking_response(monkeypatch, code):
    import urllib.error

    def reject(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.com", code, "private-token-response", {}, None)

    monkeypatch.setattr(oauth.urllib.request, "urlopen", reject)
    with pytest.raises(core.GmailError) as caught:
        oauth.identity("private-token", {"openid", "email"})
    detail = oauth.diagnostic(caught.value)
    assert detail["code"] == f"account_identity_http_{code}"
    assert "private" not in str(detail)


def test_identity_retries_transient_network_without_reauthorization(monkeypatch):
    import io

    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise OSError("temporary TLS failure")
        return io.BytesIO(b'{"email":"qa@example.com","email_verified":true}')

    monkeypatch.setattr(oauth.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
    assert oauth.identity("mock", {"openid", "email"})["email"] == "qa@example.com"
    assert len(calls) == 3


def test_missing_json_redirect_snapshot_does_not_block_cloud_auth(setup, monkeypatch):
    cloud = "https://beacon.ai-onestep.com/api/gmail/oauth/callback"
    monkeypatch.setenv("GMAIL_REDIRECT_URI", cloud)
    assert (
        setup.post("/auth/configure", headers=AUTH, json={"credentials": {"web": CREDENTIALS["installed"]}}).status_code
        == 200
    )
    response = setup.post(
        "/auth/start", headers=AUTH, json={"binding": "qa", "redirect_uri": "https://attacker.example/"}
    )
    assert response.status_code == 200
    assert parse_qs(urlsplit(response.json()["url"]).query)["redirect_uri"] == [cloud]
