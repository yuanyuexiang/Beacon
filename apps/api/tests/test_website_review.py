"""独立官网 AI 核验、状态分流和人工保护；全部使用本地证据和假传输。"""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import Operator
from app.integrations import research_judge
from app.integrations.llm import ProviderUnavailable
from app.modules.leads import places_enrichment, policy, website_review, workflows
from app.modules.leads.models import ScreeningClass
from tests.test_lead_policy import setup_lead

TEXT = "College Cafe is a coffee shop serving lunch and dinner."
DOCS = [{"id": "web0", "url": "https://old.example.org", "text": TEXT}]


class Judge:
    usage: list[dict] = []

    def judge(self, *args):
        return research_judge.Judgment(
            decision="accept",
            reason="官网公开门店身份",
            category="website",
            citations=[research_judge.Citation(document_id="web0", quote="College Cafe", kind="identity")],
        )

    def classify(self, *args):
        return research_judge.BusinessJudgment(
            category="cafe",
            reason="官网说明咖啡馆同时供应餐食",
            services=["coffee", "food_service", "takeaway"],
            citations=[research_judge.Citation(document_id="web0", quote=TEXT, kind="identity")],
        )


@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-not-real")
    monkeypatch.setattr(research_judge, "ResearchJudge", Judge)
    monkeypatch.setattr(website_review.auto_research, "pages", lambda _: DOCS)


def test_existing_website_works_without_google_and_keeps_mixed_operation(client, db, monkeypatch, ai):
    batch, lead = setup_lead(client, db)
    monkeypatch.setattr(get_settings(), "google_places_api_key", None)
    task = workflows.start(db, batch, workflows.WorkflowIn(), "tester")
    task.step = task.steps.index("google")
    task.results = [{} for _ in range(task.step)]
    result = places_enrichment.advance(db, batch, task)
    assert result["verified"] == 1 and result["done"]
    assert lead.raw["website_research"]["status"] == "verified"
    assert lead.raw["operating_type"]["services"] == ["coffee", "food_service"]
    assert "google_places_link" not in lead.raw
    assert policy.evaluate(lead, policy.Policy(cafe_action="exclude"))[0] == ScreeningClass.unchecked
    assert not website_review.needed(lead, 90)
    assert places_enrichment.advance(db, batch, task)["verified"] == 1


@pytest.mark.parametrize(
    "failure,status", [(httpx.ConnectError("SSL EOF"), "retry"), (ProviderUnavailable("bad key"), "ai_unavailable")]
)
def test_network_and_ai_failure_are_not_manual_conflicts(client, db, monkeypatch, ai, failure, status):
    _, lead = setup_lead(client, db)
    if status == "retry":
        monkeypatch.setattr(website_review.auto_research, "pages", lambda _: (_ for _ in ()).throw(failure))
    else:
        monkeypatch.setattr(research_judge, "ResearchJudge", lambda: (_ for _ in ()).throw(failure))
    assert website_review.review(db, lead, lead.website, db.scalar(select(Operator))) == status
    assert lead.raw["website_research"]["status"] == status
    assert not lead.raw.get("verified_websites")


def test_missing_or_fabricated_citation_cannot_adopt_type(client, db, monkeypatch, ai):
    _, lead = setup_lead(client, db)

    class Bad(Judge):
        def classify(self, *args):
            return research_judge.BusinessJudgment(
                category="restaurant",
                reason="猜测",
                citations=[
                    research_judge.Citation(document_id="web0", quote="A fabricated restaurant", kind="identity")
                ],
            )

    monkeypatch.setattr(research_judge, "ResearchJudge", Bad)
    assert website_review.review(db, lead, lead.website, db.scalar(select(Operator))) == "verified"
    assert lead.raw["operating_type"]["category"] == "unknown"
    assert lead.raw["operating_type"]["status"] == "insufficient"


def test_only_grounded_conflict_requires_manual_review(client, db, monkeypatch, ai):
    _, lead = setup_lead(client, db)

    class Conflict(Judge):
        def judge(self, *args):
            return research_judge.Judgment(
                decision="reject",
                reason="页面说明这是另一运营方",
                category="website",
                citations=[research_judge.Citation(document_id="web0", quote="College Cafe", kind="conflict")],
            )

    monkeypatch.setattr(research_judge, "ResearchJudge", Conflict)
    assert website_review.review(db, lead, lead.website, db.scalar(select(Operator))) == "conflict"
    assert not lead.raw.get("operating_type")


def test_manual_type_and_concurrent_edit_survive(client, db, monkeypatch, ai):
    _, lead = setup_lead(client, db)
    original = {"source": "manual", "category": "restaurant", "reason": "人工核对"}
    lead.raw = {"operating_type": original}
    db.commit()
    assert website_review.review(db, lead, lead.website, db.scalar(select(Operator))) == "verified"
    assert lead.raw["operating_type"] == original
    db.commit()

    class Editing(Judge):
        def judge(self, *args):
            lead.website = "https://human.example.org"
            db.commit()
            return super().judge(*args)

    monkeypatch.setattr(research_judge, "ResearchJudge", Editing)
    assert website_review.review(db, lead, "https://old.example.org", db.scalar(select(Operator))) == "changed"
    assert lead.website == "https://human.example.org" and lead.raw["operating_type"] == original


def test_legacy_verified_type_survives_temporary_classification_failure(client, db, monkeypatch, ai):
    _, lead = setup_lead(client, db)
    original = {
        "source": "official_website",
        "category": "restaurant",
        "citations": [{"document_id": "web0", "quote": "College Cafe"}],
        "sources": [{"id": "web0", "url": lead.website}],
    }
    lead.raw = {"operating_type": original}
    db.commit()

    class Unavailable(Judge):
        def classify(self, *args):
            raise ProviderUnavailable("temporary outage")

    monkeypatch.setattr(research_judge, "ResearchJudge", Unavailable)
    assert website_review.review(db, lead, lead.website, db.scalar(select(Operator))) == "verified"
    assert lead.raw["operating_type"] == original


def test_single_action_role_and_reason_response(client, db, monkeypatch, ai):
    _, lead = setup_lead(client, db)
    monkeypatch.setattr(get_settings(), "google_places_api_key", None)
    response = client.post(f"/api/leads/{lead.id}/website-review")
    assert response.status_code == 200, response.text
    assert response.json()["operating_type"]["category"] == "cafe"
    assert response.json()["website_research"]["judgment"]["citations"][0]["quote"] == "College Cafe"
    from tests.test_users import create, session

    user = create(client, "reader", "viewer")
    op = db.scalar(select(Operator).where(Operator.username == user["username"]))
    op.must_change_password = False
    db.commit()
    assert session(op).post(f"/api/leads/{lead.id}/website-review").status_code == 403


def test_legacy_review_can_be_retried_without_waiting_stale_days(client, db):
    _, lead = setup_lead(client, db)
    lead.raw = {"places_enrichment": {"status": "review", "checked_at": datetime.now(UTC).isoformat()}}
    assert places_enrichment.needed(lead, policy.Policy())


def test_google_candidates_use_official_evidence_instead_of_display_name_gate(client, db, monkeypatch, ai):
    from app.integrations import google_places as google
    from app.modules.leads import google_places

    _, lead = setup_lead(client, db)
    lead.website = None
    db.commit()
    monkeypatch.setattr(get_settings(), "google_places_api_key", "test")

    class Client:
        def search(self, query):
            return [
                google.Place(id="alias", displayName=google.LocalizedText(text="A different Google brand spelling"))
            ]

        def enrichment_details(self, identity):
            return google.Place(
                id=identity,
                displayName=google.LocalizedText(text="Private Google name"),
                formattedAddress="Private Google address",
                websiteUri="https://old.example.org",
            )

    monkeypatch.setattr(google_places, "_client", lambda *a, **k: Client())
    assert places_enrichment.review_one(db, lead, db.scalar(select(Operator)), policy.Policy(), "test") == "verified"
    assert lead.website == "https://old.example.org"
    assert lead.raw["google_places_link"]["place_id"] == "alias"
    assert "Private Google" not in str(lead.raw)


def test_google_budget_does_not_stop_existing_website_ai(client, db, monkeypatch, ai):
    from app.integrations import google_places as google
    from app.modules.leads import google_places
    from tests.test_imports import upload

    batch, lead = setup_lead(client, db)
    upload(client, "policy", "fhrsid,name,website\n2,Second Cafe,https://second.example.org\n")
    monkeypatch.setattr(get_settings(), "google_places_api_key", "test")

    class Capped:
        def search(self, query):
            raise google.PlacesError("quota", 429)

    monkeypatch.setattr(google_places, "_client", lambda *a, **k: Capped())
    task = workflows.start(db, batch, workflows.WorkflowIn(), "tester")
    task.params = {**task.params, "policy": {**task.params["policy"], "google_mode": "all"}}
    task.step = task.steps.index("google")
    task.results = [{} for _ in range(task.step)]
    first = places_enrichment.advance(db, batch, task)
    assert first["google_exhausted"] and first["verified"] == 1 and not first["done"]
    second = places_enrichment.advance(db, batch, task)
    assert second["verified"] == 2 and second["done"]


@pytest.mark.parametrize(
    "kind,quote", [("identity", "Fabricated statement"), ("identity", ""), ("menu", "College Cafe")]
)
def test_invalid_identity_evidence_does_not_verify(client, db, monkeypatch, ai, kind, quote):
    _, lead = setup_lead(client, db)

    class Unsupported(Judge):
        def judge(self, *args):
            return research_judge.Judgment(
                decision="accept",
                reason="没有正确身份引用",
                category="website",
                citations=[research_judge.Citation(document_id="web0", quote=quote, kind=kind)] if quote else [],
            )

    monkeypatch.setattr(research_judge, "ResearchJudge", Unsupported)
    assert website_review.review(db, lead, lead.website, db.scalar(select(Operator))) == "insufficient"
    assert not lead.raw.get("verified_websites") and not lead.raw.get("operating_type")


def test_secondary_page_failure_keeps_homepage_evidence(monkeypatch):
    from app.integrations.fetcher import FetchResult

    def fetch(url):
        if url.endswith("/about"):
            raise httpx.ConnectError("SSL EOF")
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            kind="html",
            body=b'<html>College Cafe serves lunch<a href="/about">About</a></html>',
            content_type="text/html",
        )

    monkeypatch.setattr(website_review.auto_research, "fetch", fetch)
    assert website_review.auto_research.pages("https://old.example.org")[0]["text"].startswith("College Cafe")
