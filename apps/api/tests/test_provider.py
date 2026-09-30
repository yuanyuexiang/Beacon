"""Anthropic provider：用桩客户端验证结构化结果映射、拒绝处理、无密钥时明确不可用；不调用真实 API。"""

import os
from types import SimpleNamespace

import pytest

from app.integrations.llm import AnthropicProvider, MenuTranscription, ProviderUnavailable, get_provider


class _StubClient:
    def __init__(self, parsed=None, stop_reason="end_turn", category=None):
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)
        self._parsed, self._stop, self._cat = parsed, stop_reason, category

    def _parse(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(
            parsed_output=self._parsed,
            stop_reason=self._stop,
            stop_details=SimpleNamespace(category=self._cat) if self._cat else None,
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )


def test_image_transcription_maps_items_and_observations():
    parsed = MenuTranscription.model_validate(
        dict(
            is_menu=True,
            language="en",
            items=[
                {
                    "name": "Flying Noodles – Mì Bay",
                    "price_text": "19",
                    "section": "Signature",
                    "region": "centre panel, 1st",
                },
                {"name": "Chips", "price_text": "£4.5", "section": None, "region": "right column"},
            ],
            observations=[
                {
                    "issue_code": "text_overlap",
                    "fact": "Two descriptions overlap in the Signature panel",
                    "region": "centre panel",
                    "severity": "candidate",
                }
            ],
            notes=None,
        )
    )
    stub = _StubClient(parsed)
    p = AnthropicProvider(model="claude-opus-5-5", client=stub)
    r = p.analyze_image(b"\x89PNG....", {})
    assert r.engine == "anthropic" and r.engine_version == "claude-opus-5-5"
    assert (
        r.items[0]["price"] == 19.0
        and r.items[0]["decimals"] == 0
        and r.items[0]["evidence"]["transcribed_by"] == "model"
    )
    assert r.items[1]["currency_symbol"] == "£" and r.items[1]["decimals"] == 1
    assert (
        r.issues[0]["issue_code"] == "text_overlap"
        and r.issues[0]["confirmed"] is None
        and r.issues[0]["evidence"]["observed_by"] == "model"
    )
    assert r.usage == {"input_tokens": 100, "output_tokens": 50}
    kw = stub.calls[0]
    assert (
        kw["model"] == "claude-opus-5-5"
        and kw["output_format"] is MenuTranscription
        and kw["output_config"]["effort"] == "medium"
    )
    assert (
        kw["messages"][0]["content"][0]["type"] == "image"
        and kw["messages"][0]["content"][0]["source"]["media_type"] == "image/png"
    )
    assert "Never infer allergens" in kw["system"]


def test_pdf_goes_as_document_and_not_menu_is_noted():
    parsed = MenuTranscription.model_validate(
        dict(is_menu=False, language=None, items=[], observations=[], notes="wine list")
    )
    stub = _StubClient(parsed)
    r = AnthropicProvider(client=stub).analyze_image(b"%PDF-1.4 ...", {})
    assert stub.calls[0]["messages"][0]["content"][0]["type"] == "document"
    assert r.items == [] and "不是菜单" in (r.notes or "")


def test_refusal_returns_no_facts():
    stub = _StubClient(None, stop_reason="refusal", category="general_harms")
    r = AnthropicProvider(client=stub).analyze_text("Soup 5", {})
    assert r.items == [] and r.issues == [] and "拒绝" in (r.notes or "")


def test_no_credentials_is_unavailable(monkeypatch):
    from app.core import config as cfg

    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BEACON_LLM_PROVIDER", "anthropic")
    cfg.get_settings.cache_clear()
    with pytest.raises(ProviderUnavailable):
        get_provider()
    cfg.get_settings.cache_clear()


def test_provider_endpoint_503_without_key(client, db, monkeypatch):
    from app.core import config as cfg
    from tests.test_analysis import _upload
    from tests.test_assets import setup_lead

    lead_id = setup_lead(client, db)
    aid = _upload(client, lead_id, "mini.png", "image/png")
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    os.environ["BEACON_LLM_PROVIDER"] = "anthropic"
    cfg.get_settings.cache_clear()
    r = client.post(f"/api/assets/{aid}/analyses", params={"engine": "provider"})
    os.environ.pop("BEACON_LLM_PROVIDER")
    cfg.get_settings.cache_clear()
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_provider_result_lands_as_needs_review(client, db, monkeypatch):
    """服务层：provider 结果一律 needs_review，items/issues 原样入库，usage 记入 measurements。"""
    from tests.test_analysis import _upload
    from tests.test_assets import setup_lead

    lead_id = setup_lead(client, db)
    aid = _upload(client, lead_id, "mini.png", "image/png")
    parsed = MenuTranscription.model_validate(
        dict(
            is_menu=True,
            language="en",
            items=[{"name": "Soup", "price_text": "£5", "region": "top"}],
            observations=[],
            notes=None,
        )
    )
    from app.modules.menus import service as menu_service

    monkeypatch.setattr(
        menu_service, "get_provider", lambda: AnthropicProvider(model="claude-opus-5-5", client=_StubClient(parsed))
    )
    r = client.post(f"/api/assets/{aid}/analyses", params={"engine": "provider"}).json()
    assert r["status"] == "needs_review" and r["engine"] == "anthropic" and r["engine_version"] == "claude-opus-5-5"
    assert r["items"][0]["name"] == "Soup" and r["measurements"]["usage"]["output_tokens"] == 50
