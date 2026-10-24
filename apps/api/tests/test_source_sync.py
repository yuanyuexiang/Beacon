from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import Operator
from app.integrations.google_places import Place, PlacesError
from app.modules.leads import google_places, places_enrichment, policy, source_sync, website_review, workflows
from tests.test_lead_policy import setup_lead


def test_sync_without_ai_preserves_manual_website_and_reuses_candidate(client, db, monkeypatch):
    batch, lead = setup_lead(client, db)
    monkeypatch.setattr(get_settings(), "google_places_api_key", "fake")
    monkeypatch.setattr(website_review, "review", lambda *a: pytest.fail("sync must not use AI"))
    requests = []

    class Fake:
        def search(self, query):
            requests.append("search")
            return [Place(id="candidate")]

        def enrichment_details(self, pid):
            requests.append("details")
            return Place(id=pid, websiteUri="https://new.example.org", priceLevel="PRIVATE_PRICE")

    monkeypatch.setattr(google_places, "_client", lambda *a, **kw: Fake())
    task = workflows.start(db, batch, workflows.WorkflowIn(), "tester")
    task.step = 1
    task.results = [{}]
    db.commit()
    state = source_sync.advance(db, batch, task)
    assert state["done"] and state["synced"] == 1
    assert lead.website == "https://old.example.org"
    assert "website_research" not in lead.raw and "google_places_link" not in lead.raw
    assert "PRIVATE_PRICE" not in str(lead.raw)
    assert source_sync.fresh(lead, 30)
    source_sync.advance(db, batch, task)
    assert requests == ["search", "details"]
    assert client.get(f"/api/leads/{lead.id}").json()["source_sync"]["candidates"][0]["website"]
    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "fake")
    seen = []

    def review(db, lead, url, op, pid=None):
        seen.append((url, pid))
        return "verified"

    monkeypatch.setattr(website_review, "review", review)
    places_enrichment.review_one(db, lead, db.scalar(select(Operator)), policy.Policy(), "review", force=True)
    assert seen == [("https://new.example.org", "candidate")]
    assert requests == ["search", "details"]


def test_quota_completes_sync_without_locking_list(client, db, monkeypatch):
    batch, lead = setup_lead(client, db)
    monkeypatch.setattr(get_settings(), "google_places_api_key", "fake")

    class Capped:
        def search(self, query):
            raise PlacesError("quota", 429)

    monkeypatch.setattr(google_places, "_client", lambda *a, **kw: Capped())
    task = workflows.start(db, batch, workflows.WorkflowIn(), "tester")
    task.step, task.results = 1, [{}]
    db.commit()
    workflows.advance(db, batch, task)
    assert task.status == "completed" and task.results[-1]["remaining"] == 1
    workflows.ensure_idle(db, batch)
    new = workflows.start(db, batch, workflows.WorkflowIn(phase="review", lead_ids=[lead.id]), "tester")
    assert new.steps == ["google", "screen", "contacts"]
    assert new.params["lead_ids"] == [str(lead.id)]


def test_cached_candidates_expire_and_changes_invalidate(client, db):
    _, lead = setup_lead(client, db)
    lead.raw = {
        "source_sync": {
            "status": "completed",
            "fingerprint": google_places._fingerprint(lead),
            "fetched_at": (datetime.now(UTC) - timedelta(days=31)).isoformat(),
        }
    }
    assert not source_sync.fresh(lead, 30)
    lead.raw["source_sync"]["fetched_at"] = datetime.now(UTC).isoformat()
    assert source_sync.fresh(lead, 30)
    lead.name = "Different store"
    assert not source_sync.fresh(lead, 30)


def test_overture_failure_does_not_block_google(client, db, monkeypatch):
    from app.modules.leads import service

    batch, _ = setup_lead(client, db)
    monkeypatch.setattr(service, "enrich_overture", lambda *a: (_ for _ in ()).throw(ValueError("offline")))
    task = workflows.start(db, batch, workflows.WorkflowIn(), "tester")
    workflows.advance(db, batch, task)
    assert task.step == 1 and task.status == "pending" and task.results[0]["note"]
    workflows.advance(db, batch, task)
    assert task.status == "completed"


def test_selected_review_filters_screening_and_jobs(client, db):
    from app.modules.leads import runs, service
    from app.modules.leads.models import Lead
    from tests.test_imports import upload

    batch, first = setup_lead(client, db)
    upload(client, "policy", "fhrsid,name,website\n2,Second Cafe,https://second.example.org\n")
    other = db.scalar(select(Lead).where(Lead.id != first.id))
    service.auto_screen(db, batch, lead_ids=[str(first.id)])
    db.refresh(other)
    assert not (other.raw or {}).get("screening_auto")
    run = runs.BatchRun(
        batch_id=batch.id,
        steps=["contacts"],
        status=runs.RunStatus.running,
        started_by="tester",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    runs.plan_jobs(db, run, batch, lead_ids=[str(first.id)])
    db.flush()
    assert {j.lead_id for j in db.scalars(select(runs.BatchJob).where(runs.BatchJob.run_id == run.id))} <= {first.id}
