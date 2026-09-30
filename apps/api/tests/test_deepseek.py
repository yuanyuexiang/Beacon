"""DeepSeek provider：用 httpx MockTransport 验证请求形状、JSON 解析、截断/认证/限流处理；
图片 PDF 转页图。不调用真实 API。"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.integrations.llm import DeepSeekProvider, ProviderUnavailable

FIX = Path(__file__).parent / "fixtures"
GOOD = {
    "is_menu": True,
    "language": "en",
    "items": [{"name": "Soup", "price_text": "£5.00", "section": None, "region": "top"}],
    "observations": [{"issue_code": "typo", "fact": "'Chiken' is printed", "region": "top", "severity": "candidate"}],
    "notes": None,
}


def _provider(handler, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    p = DeepSeekProvider(model="deepseek-flash", transport=httpx.MockTransport(handler))
    return p


def _ok(content, finish="stop"):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 0},
                "prompt_cache_hit_tokens": 0,
            },
        },
    )


def test_text_request_shape_and_parse(monkeypatch):
    seen: dict[str, Any] = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return _ok(json.dumps(GOOD))

    r = _provider(handler, monkeypatch).analyze_text("Soup £5.00", {})
    assert seen["url"] == "https://api.deepseek.com/chat/completions" and seen["auth"] == "Bearer test-key"
    b = seen["body"]
    assert (
        b["model"] == "deepseek-flash"
        and b["response_format"] == {"type": "json_object"}
        and b["thinking"] == {"type": "disabled"}
    )
    assert "json" in b["messages"][0]["content"].lower() and "Never infer allergens" in b["messages"][0]["content"]
    assert r.engine == "deepseek" and r.items[0]["price"] == 5.0 and r.issues[0]["issue_code"] == "typo"
    assert r.usage["input_tokens"] == 10


def test_image_and_pdf_pages(monkeypatch):
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return _ok(json.dumps(GOOD))

    p = _provider(handler, monkeypatch)
    p.analyze_image((FIX / "mini.png").read_bytes(), {})
    parts = bodies[-1]["messages"][1]["content"]
    assert parts[0]["type"] == "image_url" and parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    p.analyze_image((FIX / "two_col.pdf").read_bytes(), {"media_type": "application/pdf"})
    parts = bodies[-1]["messages"][1]["content"]
    assert parts[0]["type"] == "image_url" and parts[0]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )  # PDF 已转页图


def test_truncation_bad_json_auth_and_rate_limit(monkeypatch):
    p = _provider(lambda req: _ok('{"is_menu": true', finish="length"), monkeypatch)
    r = p.analyze_text("x", {})
    assert r.items == [] and "截断" in (r.notes or "")
    p = _provider(lambda req: _ok("not json"), monkeypatch)
    assert "无法解析" in (p.analyze_text("x", {}).notes or "")
    p = _provider(lambda req: httpx.Response(401, json={"error": "bad key"}), monkeypatch)
    with pytest.raises(ProviderUnavailable):
        p.analyze_text("x", {})
    p = _provider(lambda req: httpx.Response(429), monkeypatch)
    with pytest.raises(RuntimeError, match="限流"):
        p.analyze_text("x", {})


def test_missing_key_unavailable(monkeypatch):
    for k in ("DEEPSEEK_API_KEY", "BEACON_DEEPSEEK_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    with pytest.raises(ProviderUnavailable):
        DeepSeekProvider()
    cfg.get_settings.cache_clear()
