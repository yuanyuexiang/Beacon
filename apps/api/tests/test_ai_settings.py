"""Versioned model settings and provider contracts
synthetic data, no network or real credentials."""

import copy
import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import AuditLog
from app.integrations import ai_runtime as runtime
from app.integrations.llm import ProviderUnavailable
from app.modules.ai.configuration import decrypt
from app.modules.ai.models import AIConfiguration
from app.modules.ai.routes import Probe
from tests.test_imports import login

SECRET = "private-api-key-never-return"


def payload(provider="custom", protocol="chat", version=None):
    return {
        "version": version,
        "connections": [
            {
                "id": "test",
                "label": "Test model",
                "provider": provider,
                "protocol": protocol,
                "base_url": "https://model.example/v1",
                "model": "test-model",
                "key": SECRET,
                "vision": True,
                "enabled": True,
                "json_mode": True,
                "timeout": 20,
            }
        ],
        "routes": {"default": "test", "research": None, "writing": None, "vision": None},
    }


def save(client, body=None):
    response = client.put("/api/ai/settings", json=body or payload())
    assert response.status_code == 200, response.text
    return response.json()


def test_key_encryption_redaction_concurrency_and_permissions(client, db):
    login(client, db)
    state = save(client)
    assert SECRET not in json.dumps(state)
    row = db.scalar(select(AIConfiguration))
    cipher = row.data["connections"][0]["encrypted_key"]
    assert SECRET not in cipher and decrypt(cipher) == SECRET
    assert state["connections"][0]["key_configured"]
    assert client.get("/api/files/ai/encryption.key").status_code == 404
    assert client.put("/api/ai/settings", json=payload()).status_code == 409
    altered = payload(version=state["version"])
    altered["connections"][0].pop("key")
    altered["connections"][0]["model"] = "new-model"
    next_state = save(client, altered)
    assert runtime.client().model == "new-model"
    with runtime.scope(state["version"]):
        assert runtime.client().model == "test-model"
    altered["version"] = next_state["version"]
    altered["connections"][0]["enabled"] = False
    altered["routes"] = {}
    save(client, altered)
    with runtime.scope(state["version"]), pytest.raises(ProviderUnavailable, match="停用"):
        runtime.client()
    for log in db.scalars(select(AuditLog).where(AuditLog.action == "ai_settings_saved")):
        assert SECRET not in str(log.after)
    from app.core.models import Operator

    actor = db.scalar(select(Operator))
    actor.role = "member"
    db.commit()
    assert client.get("/api/ai/settings").status_code == 403
    assert client.put("/api/ai/settings", json=payload()).status_code == 403


def test_environment_import_uses_one_explicit_source(client, db, monkeypatch):
    login(client, db)
    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", SECRET)
    initial = client.get("/api/ai/settings").json()
    assert initial["source"] == "environment" and SECRET not in json.dumps(initial)
    assert runtime.available()
    result = client.post("/api/ai/import-environment", json={"version": None})
    assert result.status_code == 200, result.text
    state = result.json()
    assert state["source"] == "managed" and len(state["connections"]) == 1
    assert runtime.client().connection_id.startswith("imported-")
    disabled = payload(version=state["version"])
    disabled["routes"] = {}
    save(client, disabled)
    assert not runtime.available()  # Never silently falls back to an environment provider.


@pytest.mark.parametrize(
    "url",
    [
        "http://model.example",
        "https://127.0.0.1",
        "https://model.example?key=private",
        "https://user:password@model.example",
    ],
)
def test_invalid_endpoints_and_validation_do_not_echo_keys(client, db, url):
    login(client, db)
    body = payload()
    body["connections"][0]["base_url"] = url
    response = client.put("/api/ai/settings", json=body)
    assert response.status_code == 422 and SECRET not in response.text
    body["connections"][0]["key"] = SECRET * 1000
    response = client.put("/api/ai/settings", json=body)
    assert response.status_code == 422 and SECRET not in response.text


def test_test_failure_persists_and_changes_clear_old_test(client, db, monkeypatch):
    login(client, db)
    state = save(client)

    def fail(*args, **kwargs):
        raise ProviderUnavailable("AI 密钥无效（HTTP 401）")

    monkeypatch.setattr(runtime.Client, "request", fail)
    result = client.post("/api/ai/connections/test/test", json={"version": state["version"]})
    assert result.status_code == 200 and result.json()["status"] == "failed"
    stored = client.get("/api/ai/settings").json()
    assert stored["connections"][0]["test"]["checks"]["structured"]["error"].endswith("401）")
    assert SECRET not in json.dumps(client.get("/api/ai/calls").json())
    body = payload(version=state["version"])
    body["connections"][0]["model"] = "changed"
    assert not save(client, body)["connections"][0].get("test")


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
def test_provider_wire_contracts_and_sanitized_errors(protocol):
    value = {**payload(protocol=protocol)["connections"][0], "configuration_version": "snapshot"}
    seen = []

    def reply(request):
        body = json.loads(request.content)
        seen.append(body)
        assert str(request.url).startswith("https://model.example/v1/")
        if protocol == "chat":
            assert request.url.path.endswith("/chat/completions")
            assert "thinking" not in body
            assert body["response_format"] == {"type": "json_object"}
            return httpx.Response(
                200,
                json={
                    "choices": [{"finish_reason": "stop", "message": {"content": '{"value":"ok"}'}}],
                    "usage": {"prompt_tokens": 12},
                },
            )
        if protocol == "responses":
            assert request.url.path.endswith("/responses") and body["store"] is False
            assert body["text"]["format"]["schema"]["additionalProperties"] is False
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [{"content": [{"type": "output_text", "text": '{"value":"ok"}'}]}],
                },
            )
        assert request.headers["x-api-key"] == SECRET and request.url.path.endswith("/messages")
        assert body["tool_choice"]["name"] == "structured_result"
        return httpx.Response(
            200,
            json={
                "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "name": "structured_result", "input": {"value": "ok"}}],
            },
        )

    model = runtime.Client(value, httpx.MockTransport(reply))
    result = model.complete(
        [{"role": "system", "content": "Return JSON."}, {"role": "user", "content": "Return JSON value ok."}], Probe
    )
    assert Probe.model_validate_json(result.text).value == "ok" and len(seen) == 1
    model._transport = httpx.MockTransport(lambda req: httpx.Response(401, text=SECRET))
    with pytest.raises(ProviderUnavailable) as error:
        model.complete([{"role": "user", "content": "hi"}], Probe)
    assert "HTTP 401" in str(error.value) and SECRET not in str(error.value)


def test_routing_visual_checks_and_no_fallback(client, db):
    login(client, db)
    body = payload()
    writing = copy.deepcopy(body["connections"][0])
    writing.update(id="writer", model="writing-model", vision=False)
    body["connections"].append(writing)
    body["routes"]["writing"] = "writer"
    save(client, body)
    assert runtime.client("research").model == "test-model"
    assert runtime.client("writing").model == "writing-model"
    assert runtime.client("vision").model == "test-model"
    with pytest.raises(ProviderUnavailable, match="图片"):
        runtime.client("writing").complete(
            [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]}],
            Probe,
        )


def test_named_presets_model_listing_and_persistent_success(client, db, monkeypatch):
    login(client, db)
    state = save(client)
    assert {"openai", "deepseek", "anthropic", "gemini", "qwen", "doubao", "kimi", "zhipu", "custom"} <= {
        p["id"] for p in state["presets"]
    }

    def reply(self, method, path, body=None):
        if path == "models":
            return {"data": [{"id": "model-one"}, {"id": "model-two"}]}
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"value": "27"})},
                }
            ]
        }

    monkeypatch.setattr(runtime.Client, "request", reply)
    assert client.post("/api/ai/connections/test/models", json={"version": state["version"]}).json()["models"] == [
        "model-one",
        "model-two",
    ]
    result = client.post("/api/ai/connections/test/test", json={"version": state["version"]}).json()
    assert result["status"] == "passed" and result["checks"]["vision"]["status"] == "passed"
    assert client.get("/api/ai/settings").json()["connections"][0]["test"] == result


def test_unsaved_model_listing_and_saved_key_binding(client, db, monkeypatch):
    login(client, db)
    seen = []

    def listing(self, method, path, body=None):
        seen.append(self.value["key"])
        return {"data": [{"id": "beta"}, {"id": "alpha"}, {"id": "alpha"}]}

    monkeypatch.setattr(runtime.Client, "request", listing)
    draft = payload()["connections"][0]
    draft["model"] = ""
    response = client.post("/api/ai/models", json=draft)
    assert response.status_code == 200, response.text
    assert response.json()["models"] == ["alpha", "beta"]
    assert db.scalar(select(AIConfiguration)) is None
    state = save(client)
    draft.update(key="", saved_id="test", version=state["version"])
    assert client.post("/api/ai/models", json=draft).status_code == 200
    assert seen == [SECRET, SECRET]
    draft["base_url"] = "https://different.example/v1"
    assert client.post("/api/ai/models", json=draft).status_code == 422
    draft["key"] = "new-key"
    assert client.post("/api/ai/models", json=draft).status_code == 200
    draft["base_url"] = "http://127.0.0.1"
    assert client.post("/api/ai/models", json=draft).status_code == 422
    assert len(seen) == 3


def test_known_supplier_fake_dns_preserves_private_endpoint_checks(monkeypatch):
    import socket

    from app.integrations.fetcher import FetchBlocked

    def dns(ip):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [(2, 1, 6, "", (ip, 443))])

    dns("198.18.0.194")
    runtime.check_endpoint("https://api.deepseek.com/models")
    with pytest.raises(FetchBlocked):
        runtime.check_endpoint("https://custom.example/models")
    dns("127.0.0.1")
    with pytest.raises(FetchBlocked):
        runtime.check_endpoint("https://api.deepseek.com/models")
    with pytest.raises(ValueError):
        runtime.check_endpoint("http://api.deepseek.com/models")

    def unavailable(*args):
        raise socket.gaierror("failed")

    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    with pytest.raises(ProviderUnavailable, match="域名解析失败"):
        runtime.check_endpoint("https://api.deepseek.com/models")
