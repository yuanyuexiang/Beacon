"""Google 优先、时效、回退与人工保护；不调用外部服务。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import Operator
from app.integrations import google_places as google
from app.integrations import research_judge
from app.modules.leads import google_places, places_enrichment, policy, website_review
from tests.test_lead_policy import setup_lead
from tests.test_website_review import DOCS, Judge


@pytest.fixture
def scenario(client, db, monkeypatch):
    _, lead = setup_lead(client, db)
    lead.website_source = "overture:old"
    db.commit()
    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test")
    monkeypatch.setattr(get_settings(), "google_places_api_key", "test")
    monkeypatch.setattr(research_judge, "ResearchJudge", Judge)
    calls = []

    def pages(url):
        calls.append(("page", url))
        return [{**DOCS[0], "url": url}]

    monkeypatch.setattr(website_review.auto_research, "pages", pages)

    class Client:
        def search(self, query):
            calls.append(("search", query))
            return [google.Place(id="new")]

        def enrichment_details(self, identity):
            calls.append(("detail", identity))
            return google.Place(id=identity, websiteUri="https://new.example.org")

    monkeypatch.setattr(google_places, "_client", lambda *a, **kw: Client())
    return lead, db.scalar(select(Operator)), calls


@pytest.mark.parametrize("source", ["overture:old", "官网原文 AI 核验", "AI 证据核对 + 程序校验"])
def test_google_precedes_even_verified_old_website_and_refreshes_automatic(client, db, scenario, source):
    lead, op, calls = scenario
    lead.website_source = source
    website_review.review(db, lead, lead.website, op)
    db.commit()
    calls.clear()
    assert places_enrichment.review_one(db, lead, op, policy.Policy(), "test") == "verified"
    assert [x[0] for x in calls] == ["search", "detail", "page"]
    assert lead.website == "https://new.example.org"
    assert lead.raw["website_history"][0]["url"] == "https://old.example.org"
    assert lead.raw["website_history"][0]["recorded_at"]
    assert lead.raw["website_refresh_required"]["contacts"]
    assert lead.raw["verified_websites"][-1]["source"] == "google_places+official_website"
    assert not places_enrichment.needed(lead, policy.Policy())
    calls.clear()
    assert places_enrichment.review_one(db, lead, op, policy.Policy(), "test") == "verified"
    assert calls == []


@pytest.mark.parametrize("source", ["人工核对", "Google Places，人工核对", "Exa 搜索，人工核对"])
def test_manual_current_website_is_protected_but_new_candidate_visible(client, db, scenario, source):
    lead, op, _ = scenario
    lead.website_source = source
    db.commit()
    assert places_enrichment.review_one(db, lead, op, policy.Policy(), "test") == "verified"
    assert lead.website == "https://old.example.org"
    assert lead.raw["website_research"]["adoption_pending"]
    assert lead.raw["verified_websites"][-1]["url"] == "https://new.example.org"
    db.commit()
    response = client.get(f"/api/leads/{lead.id}").json()
    assert response["website_research"]["adoption_pending"]


def test_freshness_expires_and_current_website_edit_invalidates_cache(client, db, scenario):
    lead, op, calls = scenario
    places_enrichment.review_one(db, lead, op, policy.Policy(), "test")
    record = dict(lead.raw["places_enrichment"])
    record["checked_at"] = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    lead.raw = {**lead.raw, "places_enrichment": record}
    assert places_enrichment.needed(lead, policy.Policy())
    record["checked_at"] = datetime.now(UTC).isoformat()
    lead.raw = {**lead.raw, "places_enrichment": record}
    lead.website = "https://human.example.org"
    assert places_enrichment.needed(lead, policy.Policy())


def test_google_failure_keeps_old_verified_results_and_remains_retryable(client, db, monkeypatch, scenario):
    lead, op, calls = scenario

    class Unavailable:
        def search(self, query):
            raise google.PlacesError("network failure", 502)

    monkeypatch.setattr(google_places, "_client", lambda *a, **kw: Unavailable())
    assert places_enrichment.review_one(db, lead, op, policy.Policy(), "test") == "verified"
    assert lead.website == "https://old.example.org"
    assert lead.raw["places_enrichment"]["google_status"] == "retry"
    assert not lead.raw["places_enrichment"]["google_checked"]
    assert not places_enrichment.needed(lead, policy.Policy())  # 短暂退避，人工重试可强制。
    record = {**lead.raw["places_enrichment"], "checked_at": (datetime.now(UTC) - timedelta(minutes=11)).isoformat()}
    lead.raw = {**lead.raw, "places_enrichment": record}
    assert places_enrichment.needed(lead, policy.Policy())


def test_same_google_url_is_still_verified(client, db, monkeypatch, scenario):
    lead, op, calls = scenario
    lead.website = "https://new.example.org"
    db.commit()
    assert places_enrichment.review_one(db, lead, op, policy.Policy(), "test") == "verified"
    assert ("page", lead.website) in calls


def test_unverified_candidate_cannot_replace_old_website(client, db, monkeypatch, scenario):
    lead, op, calls = scenario

    class Reject(Judge):
        def judge(self, context, docs):
            if context["candidate_url"] == "https://new.example.org":
                return research_judge.Judgment(
                    decision="review", reason="没有身份锚点", category="website", citations=[]
                )
            return super().judge(context, docs)

    monkeypatch.setattr(research_judge, "ResearchJudge", Reject)
    places_enrichment.review_one(db, lead, op, policy.Policy(), "test")
    assert lead.website == "https://old.example.org"
    assert not any(x["url"] == "https://new.example.org" for x in lead.raw["verified_websites"])
    assert any(
        x["website"] == "https://new.example.org" and x["status"] == "insufficient" for x in lead.raw["website_checks"]
    )


def test_ai_only_retry_does_not_extend_google_lookup_lifetime(client, db, scenario):
    lead, op, calls = scenario
    places_enrichment.review_one(db, lead, op, policy.Policy(), "test")
    record = dict(lead.raw["places_enrichment"])
    review = {**lead.raw["website_research"], "checked_at": (datetime.now(UTC) - timedelta(days=91)).isoformat()}
    lead.raw = {**lead.raw, "website_research": review}
    db.commit()
    calls.clear()
    places_enrichment.review_one(db, lead, op, policy.Policy(), "test")
    assert [x[0] for x in calls] == ["page"]
    assert lead.raw["places_enrichment"]["checked_at"] == record["checked_at"]
    assert lead.raw["places_enrichment"]["google_status"] == "completed"


@pytest.mark.parametrize("configured", [True, False])
def test_manual_confirmation_during_google_lookup_is_not_overwritten(client, db, monkeypatch, scenario, configured):
    lead, op, _ = scenario
    if not configured:
        monkeypatch.setattr(get_settings(), "llm_provider", "fake")

    class Editing:
        def search(self, query):
            lead.raw = {**(lead.raw or {}), "website_manual": True}
            db.commit()
            return [google.Place(id="new")]

        def enrichment_details(self, identity):
            return google.Place(id=identity, websiteUri="https://new.example.org")

    monkeypatch.setattr(google_places, "_client", lambda *a, **kw: Editing())
    assert places_enrichment.review_one(db, lead, op, policy.Policy(), "test") == "changed"
    assert lead.website == "https://old.example.org" and lead.raw["website_manual"]


def test_unreadable_new_website_does_not_hide_retry_behind_old_success(client, db, monkeypatch, scenario):
    lead, op, calls = scenario

    def pages(url):
        if url == "https://new.example.org":
            raise ValueError("page unavailable")
        return DOCS

    monkeypatch.setattr(website_review.auto_research, "pages", pages)
    assert places_enrichment.review_one(db, lead, op, policy.Policy(), "test") == "verified"
    assert lead.website == "https://old.example.org"
    record = lead.raw["places_enrichment"]
    assert record["website_retry"]
    lead.raw = {
        **lead.raw,
        "places_enrichment": {**record, "checked_at": (datetime.now(UTC) - timedelta(minutes=11)).isoformat()},
    }
    assert places_enrichment.needed(lead, policy.Policy())


@pytest.mark.parametrize("source,manual", [("官网原文 AI 核验", False), ("overture:old", True)])
def test_overture_refresh_cannot_downgrade_verified_or_manual_website(client, db, scenario, source, manual):
    from app.modules.leads import service
    from app.modules.leads.models import Batch
    from tests.test_overture import PLACES

    lead, op, _ = scenario
    lead.name, lead.lat, lead.lng = "Fish Central", 51.5272, -0.0951
    lead.website_source = source
    lead.raw = {"website_manual": manual}
    db.commit()
    result = service.enrich_overture(db, db.scalar(select(Batch)), places=PLACES, overwrite=True)
    assert result["matched"] == 1 and result["website_set"] == 0
    assert lead.website == "https://old.example.org"
    assert lead.raw["overture"]["websites"]  # 原始候选仍保留。
