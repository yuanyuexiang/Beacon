"""策略配置、人工保护、Google 预算与官网证据闭环；无真实网络。"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import AuditLog, Operator
from app.integrations import google_places as google
from app.integrations import research_judge
from app.modules.leads import google_places, places_enrichment, policy, service, website_review, workflows
from app.modules.leads.models import Batch, Lead, ScreeningClass
from tests.test_imports import create_batch, login, upload


def setup_lead(client, db):
    login(client, db)
    create_batch(client, "policy")
    upload(client, "policy", "fhrsid,name,website\n1,College Cafe,https://old.example.org\n")
    return db.scalar(select(Batch)), db.scalar(select(Lead))


def test_policy_conflict_validation_and_manual_protection(client, db):
    batch, lead = setup_lead(client, db)
    original = client.get("/api/lead-policy").json()
    changed = {**original, "cafe_action": "exclude", "chain_names": ["Cafe"]}
    saved = client.put("/api/lead-policy", json=changed)
    assert saved.status_code == 200
    assert client.put("/api/lead-policy", json=changed).status_code == 409
    assert client.put("/api/lead-policy", json={**saved.json(), "stale_days": 0}).status_code == 422
    service.auto_screen(db, batch)
    assert lead.screening_class == ScreeningClass.excluded_cafe
    client.patch(f"/api/leads/{lead.id}", json={"screening_class": "candidate", "screening_reason": "人工已核对"})
    service.auto_screen(db, batch)
    db.refresh(lead)
    assert lead.screening_class == ScreeningClass.candidate
    # 手动选回待检查也必须保留。
    client.patch(f"/api/leads/{lead.id}", json={"screening_class": "unchecked"})
    assert service.auto_screen(db, batch)["preserved"] == 1


def test_legacy_automatic_exclusion_can_be_recomputed(client, db):
    batch, lead = setup_lead(client, db)
    lead.screening_class = ScreeningClass.excluded_cafe
    lead.screening_reason = "name-rule-v2: 名称含咖啡店词"
    db.commit()
    service.auto_screen(db, batch)
    assert lead.screening_class == ScreeningClass.unchecked
    assert "keep:" in lead.screening_reason
    assert "review:" in lead.screening_reason
    assert not policy.contains("Prestige Leonards", ["leon", "pret"])


def test_workflow_freezes_policy_and_google_skips_when_unconfigured(client, db):
    batch, lead = setup_lead(client, db)
    task = workflows.start(db, batch, workflows.WorkflowIn(phase="review"), "tester")
    saved = policy.current(db)
    original = task.params["policy"]
    policy.save_policy(saved.model_copy(update={"cafe_action": "exclude"}), db, db.scalar(select(Operator)))
    assert task.params["policy"] == original
    task.step = task.steps.index("google")
    task.results = [{}, {}]
    db.commit()
    result = places_enrichment.advance(db, batch, task)
    assert result["done"] and "未配置" in result["note"]


def test_minute_throttle_waits_then_continues_without_failure(client, db, monkeypatch):
    _, lead = setup_lead(client, db)
    get_settings().google_places_api_key = "test-not-real"
    operator = db.scalar(select(Operator))
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(200, json={"places": []})

    for _ in range(20):
        one = google_places._client(db, operator, lead.id, workflow_id="unlimited")
        one.transport = httpx.MockTransport(reply)
        one.search("Cafe")
    two = google_places._client(db, operator, lead.id, workflow_id="unlimited")
    two.transport = httpx.MockTransport(reply)
    waits = []

    def wait(seconds):
        waits.append(seconds)
        assert len(calls) == 20  # 不提前向 Google 请求，也不多记一次失败。
        for record in db.scalars(select(AuditLog).where(AuditLog.action == "google_places_request")):
            record.at = datetime.now(UTC) - timedelta(minutes=2)
        db.commit()

    monkeypatch.setattr(google_places.time, "sleep", wait)
    two.search("Cafe")
    assert waits == [1]
    assert len(calls) == 21  # 节流后自动继续，无需人工重试。
    get_settings().google_places_api_key = None


def test_google_chunk_saves_only_ids_and_budget_does_not_block(client, db, monkeypatch):
    batch, lead = setup_lead(client, db)
    monkeypatch.setattr(get_settings(), "google_places_api_key", "test")
    task = workflows.start(db, batch, workflows.WorkflowIn(phase="review"), "tester")
    task.step = task.steps.index("google")
    task.results = [{}]
    db.commit()

    class Client:
        def search(self, query):
            return [
                google.Place(
                    id="abc",
                    displayName=google.LocalizedText(text="Private Google Name"),
                    formattedAddress="Private address",
                )
            ]

    monkeypatch.setattr(google_places, "_client", lambda *a, **kw: Client())
    result = places_enrichment.advance(db, batch, task)
    assert result["done"] and result["ai_unavailable"] == 1
    assert lead.raw["places_enrichment"]["candidate_ids"] == ["abc"]
    assert "Private" not in str(lead.raw)
    task.results = [{}]
    task.params = {**task.params, "policy": {**task.params["policy"], "google_mode": "all"}}

    class Capped:
        def search(self, query):
            raise google.PlacesError("quota", 429)

    monkeypatch.setattr(google_places, "_client", lambda *a, **kw: Capped())
    result = places_enrichment.advance(db, batch, task)
    assert result["done"] and "quota" in result["note"]


@pytest.mark.parametrize(
    "source, manual, expected",
    [
        ("人工核对", False, "https://old.example.org"),
        ("overture:old", True, "https://old.example.org"),
        ("overture:old", False, "https://new.example.org"),
    ],
)
def test_verified_website_preserves_manual_and_type_has_exact_citations(
    client, db, monkeypatch, source, manual, expected
):
    _, lead = setup_lead(client, db)
    lead.website_source = source
    lead.raw = {"website_manual": manual}
    db.commit()
    docs = [{"id": "web0", "url": "https://new.example.org", "text": "College Cafe is an independent coffee shop."}]
    monkeypatch.setattr(website_review.auto_research, "pages", lambda _: docs)

    class Judge:
        usage = []

        def judge(self, *args):
            return research_judge.Judgment(
                decision="accept",
                reason="官网说明",
                category="website",
                citations=[research_judge.Citation(document_id="web0", quote="College Cafe", kind="identity")],
            )

        def classify(self, *args):
            return research_judge.BusinessJudgment(
                category="cafe",
                reason="官网明确说明",
                citations=[
                    research_judge.Citation(document_id="web0", quote="independent coffee shop", kind="identity")
                ],
            )

    monkeypatch.setattr(research_judge, "ResearchJudge", Judge)
    place = google.Place(
        id="verified", displayName=google.LocalizedText(text=lead.name), websiteUri="https://new.example.org"
    )
    assert places_enrichment.verify_website(db, lead, place, db.scalar(select(Operator)))
    db.commit()
    assert lead.website == expected
    assert lead.raw["website_history"][0]["url"] == "https://old.example.org"
    assert lead.raw["verified_websites"][0]["url"] == "https://new.example.org"
    assert lead.raw["operating_type"]["category"] == "cafe"
    assert lead.raw["google_places_link"]["place_id"] == "verified"
    assert client.get(f"/api/leads/{lead.id}").json()["operating_type"]["category"] == "cafe"
    # Google 名称差异不能推翻已验证的独立官网身份。
    place.displayName.text = "Other company"
    assert places_enrichment.verify_website(db, lead, place, db.scalar(select(Operator)))


def test_needed_includes_existing_overture_and_review(client, db):
    _, lead = setup_lead(client, db)
    selected = policy.Policy()
    assert places_enrichment.needed(lead, selected)
    lead.raw = {"places_enrichment": {"status": "verified", "checked_at": datetime.now(UTC).isoformat()}}
    assert places_enrichment.needed(lead, selected)  # 旧策略不能证明已查询当前官网。
    places_enrichment._save_status(lead, "verified", "Google 已查询", [], google_status="completed")
    assert not places_enrichment.needed(lead, selected)
    lead.raw = {"places_enrichment": {"status": "review", "checked_at": datetime.now(UTC).isoformat()}}
    assert places_enrichment.needed(lead, selected)


def test_google_chunk_resume_does_not_repeat_completed_leads(client, db, monkeypatch):
    batch, lead = setup_lead(client, db)
    upload(client, "policy", "fhrsid,name\n2,Other Cafe\n3,Third Cafe\n")
    monkeypatch.setattr(get_settings(), "google_places_api_key", "test")
    task = workflows.start(db, batch, workflows.WorkflowIn(phase="review"), "tester")
    task.step = task.steps.index("google")
    task.results = [{}]
    db.commit()
    calls = []

    class Client:
        def search(self, query):
            calls.append(query)
            return []

    monkeypatch.setattr(google_places, "_client", lambda *args, **kwargs: Client())
    one = places_enrichment.advance(db, batch, task)
    assert not one["done"] and len(calls) == 2
    two = places_enrichment.advance(db, batch, task)
    assert two["done"] and two["insufficient"] == 3
    assert len(calls) == len(set(calls)) == 3
    assert not places_enrichment.advance(db, batch, task)["failed"]
    assert len(calls) == 3


def test_verified_operating_type_takes_priority_over_name_keywords(client, db):
    _, lead = setup_lead(client, db)
    selected = policy.Policy(cafe_action="exclude", institution_action="exclude")
    assert policy.evaluate(lead, selected)[0] == ScreeningClass.excluded_institution
    lead.raw = {"operating_type": {"category": "restaurant", "citations": [{"quote": "a restaurant"}]}}
    assert policy.evaluate(lead, selected)[0] == ScreeningClass.unchecked
    lead.raw = {"operating_type": {"category": "cafe", "citations": [{"quote": "a cafe"}]}}
    cls, reason, _ = policy.evaluate(lead, selected)
    assert cls == ScreeningClass.excluded_cafe and "官网原文" in reason


@pytest.mark.parametrize(
    "note",
    [
        "本次任务 Google 调用预算已用完，剩余门店可另开补充任务",
        "Google 查询次数已达上限，请稍后或次日重试",
    ],
)
def test_old_exhausted_workflow_can_continue_without_new_task(client, db, monkeypatch, note):
    batch, lead = setup_lead(client, db)
    monkeypatch.setattr(get_settings(), "google_places_api_key", "test")
    task = workflows.start(db, batch, workflows.WorkflowIn(phase="review"), "tester")
    task.step = task.steps.index("google")
    lead.raw = {
        "places_enrichment": {
            "strategy_version": places_enrichment.STRATEGY_VERSION,
            "google_status": "retry",
            "status": "retry",
            "reason": note,
            "website": lead.website,
            "manual": website_review.manual(lead),
            "checked_at": datetime.now(UTC).isoformat(),
        }
    }
    task.params = {**task.params, "policy": {**task.params["policy"], "google_request_limit": 20}}
    task.results = [{"processed": [str(lead.id)], "google_exhausted": True, "note": note}]
    db.commit()
    calls = []

    def review(*args):
        calls.append(str(args[1].id))
        args[1].raw = {"places_enrichment": {"status": "insufficient", "google_status": "completed"}}
        return "insufficient"

    monkeypatch.setattr(places_enrichment, "review_one", review)
    result = places_enrichment.advance(db, batch, task)
    assert calls == [str(lead.id)] and result["done"]
    assert "google_exhausted" not in result and "note" not in result
    assert "google_request_limit" not in policy.Policy.model_validate(task.params["policy"]).model_dump()


def test_minute_wait_can_be_cancelled_without_upstream_call(client, db, monkeypatch):
    batch, lead = setup_lead(client, db)
    monkeypatch.setattr(get_settings(), "google_places_api_key", "test-not-real")
    task = workflows.start(db, batch, workflows.WorkflowIn(phase="review"), "tester")
    operator = db.scalar(select(Operator))
    c = google_places._client(db, operator, lead.id, workflow_id=str(task.id))
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(200, json={"places": []})

    c.transport = httpx.MockTransport(reply)
    for _ in range(20):
        c.search("Cafe")
    waits = []

    def cancel(seconds):
        waits.append(seconds)
        task.status = "cancelled"
        db.commit()

    monkeypatch.setattr(google_places.time, "sleep", cancel)
    with pytest.raises(google.PlacesError, match="任务已结束"):
        c.search("Cafe")
    assert waits == [1] and len(calls) == 20
