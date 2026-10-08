"""脱敏 MCP 夹具，无网络；搜索不写官网，确认需人工核对。"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.models import AuditLog
from app.integrations import exa
from app.modules.leads.models import Lead
from tests.test_imports import CSV_A, create_batch, login, upload

TEXT = """Title: Vesper
URL: https://vesper.example/contact
Published: N/A
Highlights:
Vesper, 8-10 Exmouth Market, EC1R 4QA. Menu

---

Title: Vesper Concept
URL: https://vesper-concept.lovable.app/
Highlights:
8-10 Exmouth Market EC1R 4QA

---

Title: Directory
URL: https://exa.ai/library/place/vesper
Highlights:
Vesper

---

Title: Internal
URL: http://127.0.0.1/
Highlights:
Internal
"""
RESULT = {"content": [{"type": "text", "text": TEXT}]}


def _transport(result=RESULT, *, sse=True, status=200):
    def handler(request):
        assert str(request.url) == exa.ENDPOINT
        assert request.method == "POST"
        assert json.loads(request.content)["params"]["name"] == "web_search_exa"
        message = {"jsonrpc": "2.0", "id": 1, "result": result}
        body = "event: message\ndata: " + json.dumps(message) + "\n\n" if sse else json.dumps(message)
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("sse", [True, False])
def test_mcp_formats_and_unsafe_urls(sse):
    got = exa.search("Vesper EC1R 4QA", transport=_transport(sse=sse))
    assert len(got) == 3 and got[0]["url"] == "https://vesper.example/contact"
    assert "EC1R 4QA" in got[0]["excerpt"]


@pytest.mark.parametrize("status,expected", [(429, 429), (401, 503), (403, 503), (500, 502)])
def test_http_errors_safe_and_actionable(status, expected):
    with pytest.raises(exa.SearchError) as e:
        exa.search("Vesper", "secret-test-key", transport=_transport(status=status))
    assert e.value.status == expected and "secret-test-key" not in str(e.value)


def test_rate_limit_in_success_response_and_empty_results():
    limited = {"_meta": {"ai.exa/rateLimited": True}, "content": [{"type": "text", "text": "limit"}]}
    with pytest.raises(exa.SearchError) as e:
        exa.search("Vesper", transport=_transport(limited))
    assert e.value.status == 429
    assert exa.search("Vesper", transport=_transport({"content": []})) == []
    with pytest.raises(exa.SearchError):
        exa.search("Vesper", transport=_transport({"content": [{"type": "text", "text": "unexpected format"}]}))


@pytest.mark.parametrize("content", [[None], [{"type": "text", "text": None}], "bad"])
def test_malformed_upstream_content_is_safe_error(content):
    with pytest.raises(exa.SearchError, match="格式异常"):
        exa.search("Vesper", transport=_transport({"content": content}))


def test_api_key_only_in_header_timeout_and_size_limit():
    def handler(request):
        assert request.headers["x-api-key"] == "secret-test-key"
        assert "secret-test-key" not in str(request.url) and "secret-test-key" not in request.content.decode()
        raise httpx.ReadTimeout("timeout with sensitive upstream data", request=request)

    with pytest.raises(exa.SearchError) as e:
        exa.search("Vesper", "secret-test-key", transport=httpx.MockTransport(handler))
    assert e.value.status == 504 and "sensitive" not in str(e.value)
    with pytest.raises(exa.SearchError, match="大小上限"):
        exa.search(
            "Vesper", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (exa.MAX_BYTES + 1)))
        )


def _setup(client, db, monkeypatch):
    login(client, db)
    create_batch(client)
    upload(client, "b1", CSV_A)
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    lead.raw = {**(lead.raw or {}), "contacts_scan": {"website": None, "pages_ok": 0}}
    db.commit()
    monkeypatch.setattr(exa, "search", lambda q, key: exa.parse_candidates(RESULT))
    return str(lead.id)


def _confirm(result, **changes):
    return {
        "search_id": result["search_id"],
        "candidate_id": result["candidates"][0]["id"],
        "address_checked": True,
        "official_checked": True,
        "evidence": "官网联系页地址8-10 Exmouth Market EC1R 4QA匹配",
        "expected_website": None,
        **changes,
    }


def test_search_candidates_then_manual_confirmation(client, db, monkeypatch):
    lead_id = _setup(client, db, monkeypatch)
    assert client.get(f"/api/leads/{lead_id}/website-search").json() is None
    r = client.post(f"/api/leads/{lead_id}/website-search", json={})
    assert r.status_code == 200
    result = r.json()
    assert "Vesper" in result["query"] and "EC1R 4QA" in result["query"]
    assert result["candidates"][0]["postcode_seen"] is True
    assert result["candidates"][1]["warnings"] and result["candidates"][2]["warnings"]
    assert client.get(f"/api/leads/{lead_id}").json()["website"] is None
    assert client.get(f"/api/leads/{lead_id}/website-search").json() == result
    r = client.post(f"/api/leads/{lead_id}/website-confirm", json=_confirm(result))
    assert r.status_code == 200 and r.json()["website"] == result["candidates"][0]["url"]
    db.expire_all()
    lead = db.get(Lead, uuid.UUID(lead_id))
    assert lead.raw["contacts_scan"] == {"website": None, "pages_ok": 0}
    assert lead.raw["website_confirmation"]["reviewed_by"] == "tester"
    assert lead.website_source == "Exa 搜索，人工核对"
    assert client.get(f"/api/leads/{lead_id}/eligibility").json() == []
    log = db.scalar(select(AuditLog).where(AuditLog.action == "confirm_website"))
    assert log.before["website"] is None and log.after["evidence"]


def test_checks_evidence_current_search_and_website_conflict(client, db, monkeypatch):
    lead_id = _setup(client, db, monkeypatch)
    result = client.post(f"/api/leads/{lead_id}/website-search", json={}).json()
    endpoint = f"/api/leads/{lead_id}/website-confirm"
    assert client.post(endpoint, json=_confirm(result, address_checked=False)).status_code == 400
    assert client.post(endpoint, json=_confirm(result, official_checked=False)).status_code == 400
    assert client.post(endpoint, json=_confirm(result, evidence="  ")).status_code == 422
    assert client.post(endpoint, json=_confirm(result, candidate_id="forged")).status_code == 400
    latest = client.post(f"/api/leads/{lead_id}/website-search", json={"query": "Vesper London"}).json()
    assert client.post(endpoint, json=_confirm(result)).status_code == 409
    client.patch(f"/api/leads/{lead_id}", json={"website": "https://other.example/"})
    assert client.post(endpoint, json=_confirm(latest)).status_code == 409
    assert client.get(f"/api/leads/{lead_id}").json()["website"] == "https://other.example/"


def test_expired_candidates_and_search_failure_preserve_previous(client, db, monkeypatch):
    lead_id = _setup(client, db, monkeypatch)
    result = client.post(f"/api/leads/{lead_id}/website-search", json={}).json()
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    db.refresh(lead)
    result["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    lead.raw = {**lead.raw, "website_search": result}
    db.commit()
    assert client.post(f"/api/leads/{lead_id}/website-confirm", json=_confirm(result)).status_code == 409

    def failed(*args):
        raise exa.SearchError("Exa 搜索限流", 429)

    monkeypatch.setattr(exa, "search", failed)
    assert client.post(f"/api/leads/{lead_id}/website-search", json={}).status_code == 429
    assert client.get(f"/api/leads/{lead_id}/website-search").json() == result


def test_auth_and_nonexistent_lead(client, db):
    zero = "00000000-0000-0000-0000-000000000000"
    for method, path in [("get", "website-search"), ("post", "website-search"), ("post", "website-confirm")]:
        assert getattr(client, method)(f"/api/leads/{zero}/{path}").status_code == 401
    login(client, db)
    assert client.get(f"/api/leads/{zero}/website-search").status_code == 404
    assert client.post(f"/api/leads/{zero}/website-search", json={}).status_code == 404
