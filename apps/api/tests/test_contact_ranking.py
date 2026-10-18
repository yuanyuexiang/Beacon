"""联系方式用途筛选：真实抽取证据 + 假模型响应；无网络或真实触达。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.integrations import research_judge as rj
from app.integrations import website_contacts as wc
from app.modules.leads.models import Lead
from app.modules.sales import contact_ranking as ranking
from app.modules.sales import contacts
from tests.test_contacts import SITE, _lead_id, _web_transport

TEXT = "Vesper Restaurant. Business enquiries: 0800 833551. Press office: 01224 348534. Booking: 020 7946 0123."


def found():
    return {
        "website": {"identity_documents": [{"id": "page0", "url": SITE, "text": TEXT}]},
        "candidates": [
            {
                "id": ranking.candidate_id("phone", value),
                "kind": "phone",
                "channel": "phone",
                "value": value,
                "sources": [{"type": "website", "ref": SITE}],
                "evidence": [{"page_url": SITE, "text": TEXT}],
            }
            for value in ["+44800833551", "+441224348534", "+442079460123"]
        ],
    }


def decision(candidate, purpose="business", affiliation="target", recommendation="recommended", quote=TEXT):
    return rj.ContactDecision(
        candidate_id=candidate["id"],
        recommendation=recommendation,
        affiliation=affiliation,
        owner="Vesper",
        purpose=purpose,
        reason="官网说明所属门店及用途",
        citations=[rj.Citation(document_id=f"{candidate['id']}_0", quote=quote, kind="identity")],
    )


@pytest.fixture
def judge(monkeypatch):
    class Judge:
        model = "test-grounded-contact-model"
        usage = []

        def select_contacts(self, task, docs):
            choices = []
            for c in task["candidates"]:
                own = c["evidence_ids"]
                if not own:
                    continue
                purpose = (
                    "media"
                    if c["value"] == "+441224348534"
                    else "booking"
                    if c["value"] == "+442079460123"
                    else "general"
                )
                choices.append(
                    rj.ContactDecision(
                        candidate_id=c["candidate_id"],
                        recommendation="recommended",
                        affiliation="target",
                        owner="Vesper",
                        purpose=purpose,  # type: ignore[arg-type]
                        reason="来自官网公开联系方式上下文",
                        citations=[
                            rj.Citation(
                                document_id=own[0],
                                quote=next(d["text"] for d in docs if d["id"] == own[0]),
                                kind="identity",
                            )
                        ],
                    )
                )
            return rj.ContactJudgment(decisions=choices)

    monkeypatch.setattr(rj, "ResearchJudge", Judge)
    return Judge


def test_role_guard_and_no_phone_prefix_bias(monkeypatch, judge):
    f = found()
    result = ranking.rank(SimpleNamespace(name="Vesper", address=None, postcode=None, website=SITE), f)
    assert result["status"] == "completed"
    assert [c["assessment"]["recommendation"] for c in f["candidates"]] == ["recommended", "not_recommended", "backup"]
    assert f["candidates"][0]["assessment"]["citations"][0]["url"] == SITE


@pytest.mark.parametrize("failure", ["invented_id", "duplicate_id", "fabricated_quote", "other_candidate_quote"])
def test_untrusted_output_cannot_promote_candidate(monkeypatch, failure):
    f = found()

    class Bad:
        model = "test"
        usage = []

        def select_contacts(self, *args):
            d = decision(f["candidates"][0])
            if failure == "invented_id":
                d.candidate_id = "new-unseen-number"
            elif failure == "fabricated_quote":
                d.citations[0].quote = "Imaginary restaurant owner"
            elif failure == "other_candidate_quote":
                d.citations[0].document_id = f"{f['candidates'][1]['id']}_0"
            return rj.ContactJudgment(decisions=[d, d] if failure == "duplicate_id" else [d])

    monkeypatch.setattr(rj, "ResearchJudge", Bad)
    ranking.rank(SimpleNamespace(name="Vesper", address=None, postcode=None, website=SITE), f)
    assert all(c["assessment"]["recommendation"] == "review" for c in f["candidates"])


def test_overture_only_or_unknown_ownership_not_recommended(monkeypatch, judge):
    f = found()
    f["candidates"][0]["evidence"] = []
    ranking.rank(SimpleNamespace(name="Vesper", address=None, postcode=None, website=SITE), f)
    assert f["candidates"][0]["assessment"]["recommendation"] == "review"


def test_same_contact_keeps_later_page_context():
    from app.integrations.fetcher import FetchResult

    def fetch(url):
        body = (
            '<h1>Vesper</h1><a href="/contact">Contact</a><a href="tel:02079460123">Call</a>'
            if url == SITE
            else "<h1>Vesper owner</h1><p>Business: 020 7946 0123</p>"
        )
        return FetchResult(
            url=url, final_url=url, status=200, kind="html", body=body.encode(), content_type="text/html"
        )

    scan = wc.scan(SITE, fetch)
    phone = next(c for c in scan["contacts"] if c["kind"] == "phone")
    assert len({e["page_url"] for e in phone["evidence"]}) == 2
    assert any("Business" in e["text"] for e in phone["evidence"])


def test_single_and_batch_use_same_review_preserving_old_eligibility(client, db, monkeypatch, judge):
    import functools

    from app.integrations import fetcher

    monkeypatch.setattr(fetcher, "_is_public_host", lambda *a, **kw: True)
    html = f"<h1>Vesper Restaurant</h1><p>{TEXT}</p>"
    monkeypatch.setattr(
        contacts, "scan_website", functools.partial(contacts.scan_website, web_transport=_web_transport({"/": html}))
    )
    lead_id = _lead_id(client, db)
    client.post(
        f"/api/leads/{lead_id}/eligibility",
        json={"channel": "phone", "contact_ref": "+441224348534", "eligibility": "blocked"},
    )
    response = client.post(f"/api/leads/{lead_id}/contact-review")
    assert response.status_code == 200, response.text
    assert response.json()["candidates"][0]["assessment"]["recommendation"] == "recommended"
    assert len(client.get(f"/api/leads/{lead_id}/eligibility").json()) == 1  # 推荐操作本身不记录渠道。
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    result = contacts.collect(db, lead)
    db.commit()
    assert result["recorded"] == 1 and result["recommended"] == 1
    rows = {e["contact_ref"]: e for e in client.get(f"/api/leads/{lead_id}/eligibility").json()}
    assert rows["+44800833551"]["eligibility"] == "unknown"
    assert rows["+441224348534"]["eligibility"] == "blocked"
    assert rows["+441224348534"]["recommendation"]["recommendation"] == "not_recommended"
    assert "+442079460123" not in rows


def test_single_review_preserves_concurrent_manual_website(client, db, monkeypatch, judge):
    lead_id = _lead_id(client, db)
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    scan = {
        "pages": [],
        "contacts": [
            {"kind": "phone", "value": "+44800833551", "page_url": SITE, "evidence": [{"page_url": SITE, "text": TEXT}]}
        ],
    }
    monkeypatch.setattr(contacts, "scan_website", lambda *args: scan)

    base = judge()

    class Editing:
        model = "test"
        usage = []

        def select_contacts(self, *args):
            lead.website = "https://human.example"
            db.commit()
            return base.select_contacts(*args)

    monkeypatch.setattr(rj, "ResearchJudge", Editing)
    response = client.post(f"/api/leads/{lead_id}/contact-review")
    assert response.status_code == 409
    db.refresh(lead)
    assert lead.website == "https://human.example" and not (lead.raw or {}).get("contact_review")


@pytest.mark.parametrize("unsupported", ["owner", "citation_kind"])
def test_unspecified_owner_or_wrong_evidence_kind_stays_pending(monkeypatch, unsupported):
    f = found()

    class Bad:
        model = "test"
        usage = []

        def select_contacts(self, *args):
            d = decision(f["candidates"][0])
            if unsupported == "owner":
                d.owner = ""
            else:
                d.citations[0].kind = "date"
            return rj.ContactJudgment(decisions=[d])

    monkeypatch.setattr(rj, "ResearchJudge", Bad)
    ranking.rank(SimpleNamespace(name="Vesper", address=None, postcode=None, website=SITE), f)
    assert f["candidates"][0]["assessment"]["recommendation"] == "review"


def test_new_review_endpoint_rejects_viewer(client, db):
    from app.core.models import Operator
    from tests.test_users import create, session

    lead_id = _lead_id(client, db)
    user = create(client, "contact-reader", "viewer")
    op = db.scalar(select(Operator).where(Operator.username == user["username"]))
    op.must_change_password = False
    db.commit()
    assert session(op).post(f"/api/leads/{lead_id}/contact-review").status_code == 403


def test_suppression_added_during_ai_is_rechecked_before_collect(client, db, monkeypatch, judge):
    lead_id = _lead_id(client, db)
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    scan = {
        "pages": [],
        "contacts": [
            {"kind": "phone", "value": "+44800833551", "page_url": SITE, "evidence": [{"page_url": SITE, "text": TEXT}]}
        ],
    }
    monkeypatch.setattr(contacts, "scan_website", lambda *args: scan)
    blocked = False
    monkeypatch.setattr(contacts.service, "is_suppressed", lambda *args: object() if blocked else None)
    base = judge()

    class Suppressing:
        model = "test"
        usage = []

        def select_contacts(self, *args):
            nonlocal blocked
            blocked = True
            return base.select_contacts(*args)

    monkeypatch.setattr(rj, "ResearchJudge", Suppressing)
    result = contacts.collect(db, lead)
    db.commit()
    assert result["recorded"] == 0
    assert client.get(f"/api/leads/{lead_id}/eligibility").json() == []


def test_contact_schema_real_adapter_repairs_fabricated_citation_once(monkeypatch):
    import json

    import httpx

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-not-real")
    f = found()
    valid = decision(f["candidates"][0])
    calls = []

    def reply(request):
        body = json.loads(request.content)
        assert any("json" in m["content"].lower() for m in body["messages"]), (
            "DeepSeek JSON mode requires json in prompt"
        )
        calls.append(body)
        d = valid.model_copy(deep=True)
        if len(calls) == 1:
            d.citations[0].quote = "Invented procurement owner"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": rj.ContactJudgment(decisions=[d]).model_dump_json()},
                    }
                ],
                "usage": {"total_tokens": 10},
            },
        )

    judge = rj.ResearchJudge(transport=httpx.MockTransport(reply))
    result = judge.select_contacts(
        {"candidates": [f["candidates"][0]]}, [{"id": f"{valid.candidate_id}_0", "url": SITE, "text": TEXT}]
    )
    assert len(calls) == 2 and result.decisions[0].citations[0].quote == TEXT
    assert len(judge.usage) == 2


def test_configured_request_error_is_not_reported_as_missing_key(monkeypatch):
    from app.core.config import get_settings
    from app.integrations.llm import ProviderUnavailable

    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-not-real")

    class Failing:
        def select_contacts(self, *args):
            raise ProviderUnavailable("AI 证据判断失败：HTTP 400")

    monkeypatch.setattr(rj, "ResearchJudge", Failing)
    result = ranking.rank(SimpleNamespace(name="Vesper", address=None, postcode=None, website=SITE), found())
    assert "AI 已配置" in result["reason"] and "HTTP 400" in result["reason"]
    assert "未配置" not in result["reason"]
