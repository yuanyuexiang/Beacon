"""Read-only AI assistance, no external model or phone actions."""

import json
from types import SimpleNamespace

import pytest

from app.integrations.llm import ProviderUnavailable
from app.modules.mobile import assistance


@pytest.fixture(autouse=True)
def operator(client, db):
    from tests.test_imports import login

    login(client, db)


@pytest.fixture
def page():
    return {
        "channel": "facebook",
        "own_profile": True,
        "nodes": [
            {"id": 1, "text": "编辑个人主页"},
            {"id": 2, "text": "Test Person"},
        ],
    }


def headers(client):
    code = client.post("/api/mobile/pairing").json()["code"]
    paired = client.post("/api/mobile/device/pair", json={"code": code, "label": "Test"}).json()
    return {"Authorization": "Bearer " + paired["token"]}, paired["device_id"]


def fake(monkeypatch, result):
    class Model:
        model, name, connection_id, version = "test-model", "test", "test-connection", "test-version"

        def complete(self, messages, schema, max_tokens):
            assert "Test Person" in messages[1]["content"]
            return SimpleNamespace(text=json.dumps(result), usage={"total_tokens": 12})

    monkeypatch.setattr(assistance.ai_runtime, "client", lambda purpose: Model())


def test_page_assistance_returns_only_existing_node_and_no_account_write(client, db, monkeypatch, page):
    from app.modules.mobile.models import Device

    h, identity = headers(client)
    fake(monkeypatch, {"kind": "identity", "node_id": 2, "confidence": "high"})
    r = client.post("/api/mobile/device/account-assistance", headers=h, json=page)
    assert r.status_code == 200, r.text
    assert r.json()["identity"] == "Test Person"
    assert r.json()["model"] == "test-model"
    db.expire_all()
    import uuid

    assert db.get(Device, uuid.UUID(identity)).account is None


@pytest.mark.parametrize(
    "result",
    [
        {"kind": "identity", "node_id": 999, "confidence": "high"},
        {"kind": "identity", "node_id": 1, "confidence": "high"},
        {"kind": "identity", "node_id": 2, "confidence": "low"},
        {"kind": "ambiguous", "node_id": None, "confidence": "high"},
    ],
)
def test_ai_cannot_invent_or_confirm_ambiguous_identity(client, monkeypatch, page, result):
    h, _ = headers(client)
    fake(monkeypatch, result)
    r = client.post("/api/mobile/device/account-assistance", headers=h, json=page)
    assert r.json()["status"] == "needs_action"
    assert "identity" not in r.json()


def test_no_model_call_without_own_profile_or_when_revoked(client, monkeypatch, page):
    h, identity = headers(client)
    monkeypatch.setattr(assistance.ai_runtime, "client", lambda purpose: pytest.fail("must not call model"))
    page["own_profile"] = False
    assert client.post("/api/mobile/device/account-assistance", headers=h, json=page).json()["status"] == "needs_action"
    client.post(f"/api/mobile/devices/{identity}/revoke")
    assert client.post("/api/mobile/device/account-assistance", headers=h, json=page).status_code == 401
    assert client.post("/api/mobile/device/account-assistance", json=page).status_code == 401


def test_unavailable_model_and_bounded_input(client, monkeypatch, page):
    h, _ = headers(client)

    def unavailable(purpose):
        raise ProviderUnavailable("模型未配置")

    monkeypatch.setattr(assistance.ai_runtime, "client", unavailable)
    assert client.post("/api/mobile/device/account-assistance", headers=h, json=page).json() == {
        "status": "unavailable",
        "detail": "模型未配置",
    }
    page["nodes"][0]["text"] = "x" * 161
    assert client.post("/api/mobile/device/account-assistance", headers=h, json=page).status_code == 422


def test_mobile_purpose_uses_selected_connection(client, db):
    from app.modules.ai import configuration
    from tests.test_ai_settings import payload

    body = payload()
    body["routes"]["mobile"] = "test"
    response = client.put("/api/ai/settings", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["routes"]["mobile"] == "test"
    assert configuration.PURPOSES["mobile"] == "手机页面理解"
    selected = assistance.ai_runtime.selected("mobile")
    assert selected is not None
    assert selected["model"] == "test-model"
