import uuid

from sqlalchemy import select

from app.integrations.research_judge import Citation, ResearchJudge
from app.modules.sales.assistance import ReplyAdvice, SalesBrief
from app.modules.sales.models import Event, Suppression
from tests.test_imports import create_batch, login, upload


def setup(client, db):
    login(client, db)
    create_batch(client)
    upload(client, "b1", "fhrsid,name\n100,Sample Cafe\n")
    return client.get("/api/leads?batch_key=b1").json()[0]["id"]


def test_brief_read_does_not_call_model_and_changed_facts_stale(client, db, monkeypatch):
    lead_id = setup(client, db)
    monkeypatch.setattr(ResearchJudge, "__init__", lambda self: setattr(self, "model", "mock"))
    calls = []

    def judge(self, task, docs, schema, system):
        calls.append(docs)
        return SalesBrief(
            summary="登记为 Sample Cafe",
            approach="先询问菜单负责人",
            gaps=["未核对菜单"],
            citations=[Citation(document_id="store", quote="Sample Cafe", kind="identity")],
        )

    monkeypatch.setattr(ResearchJudge, "_judge", judge)
    path = f"/api/leads/{lead_id}/sales-brief"
    assert client.get(path).json()["result"] is None
    assert not calls
    assert client.post(path).status_code == 200
    assert client.get(path).json()["stale"] is False
    assert len(calls) == 1
    from app.modules.leads.models import Lead

    lead = db.get(Lead, uuid.UUID(lead_id))
    lead.name = "Changed cafe"
    db.commit()
    assert client.get(path).json()["stale"] is True


def test_reply_rejection_suppresses_idempotently_and_never_suggests_send(client, db, monkeypatch):
    lead_id = setup(client, db)
    monkeypatch.setattr(ResearchJudge, "__init__", lambda self: setattr(self, "model", "mock"))
    monkeypatch.setattr(
        ResearchJudge,
        "_judge",
        lambda *a: ReplyAdvice(
            intent="unsubscribe",
            summary="请求停止联系",
            suggested_reply="must be removed",
            citations=[Citation(document_id="reply", quote="Stop emailing me", kind="identity")],
        ),
    )
    path = f"/api/leads/{lead_id}/reply-advice"
    for _ in range(2):
        response = client.post(path, json={"body": "Stop emailing me", "channel": "email"})
        assert response.status_code == 200, response.text
        assert response.json()["suggested_reply"] == ""
    assert len(db.scalars(select(Suppression)).all()) == 1
    assert len(db.scalars(select(Event)).all()) == 2


def test_model_failure_still_records_reply(client, db, monkeypatch):
    lead_id = setup(client, db)

    def fail(self):
        raise ValueError("offline")

    monkeypatch.setattr(ResearchJudge, "__init__", fail)
    response = client.post(f"/api/leads/{lead_id}/reply-advice", json={"body": "Please send information"})
    assert response.status_code == 503
    events = db.scalars(select(Event)).all()
    assert len(events) == 1 and events[0].kind.value == "reply"
    assert "Please send information" not in str(events[0].payload)


def test_followup_draft_requires_confirmation_and_metrics_are_explicit(client, db, monkeypatch):
    lead_id = setup(client, db)
    monkeypatch.setattr(ResearchJudge, "__init__", lambda self: setattr(self, "model", "mock"))
    monkeypatch.setattr(
        ResearchJudge,
        "_judge",
        lambda *a: ReplyAdvice(
            intent="quote",
            summary="询问报价",
            suggested_reply="Could you share the required quantity?",
            citations=[Citation(document_id="reply", quote="Please send a quote", kind="identity")],
        ),
    )
    reply = client.post(f"/api/leads/{lead_id}/reply-advice", json={"body": "Please send a quote"}).json()
    event = db.get(Event, uuid.UUID(reply["event_id"]))
    assert "intent" not in event.payload
    assert client.post(f"/api/leads/{lead_id}/reply-confirm", json={"event_id": reply["event_id"]}).status_code == 200
    db.refresh(event)
    assert event.payload["intent"] == "quote"
    body = {
        "event_id": reply["event_id"],
        "sender_identity": "Example company",
        "opt_out_text": "Please tell us to stop.",
    }
    first = client.post(f"/api/leads/{lead_id}/reply-draft", json=body)
    assert first.status_code == 200, first.text
    second = client.post(f"/api/leads/{lead_id}/reply-draft", json=body)
    assert first.json() == second.json()
    from app.modules.content.models import ContentPiece

    piece = db.get(ContentPiece, uuid.UUID(first.json()["id"]))
    assert piece.status.value == "draft" and not piece.approvals
    assert body["sender_identity"] in piece.body_text and body["opt_out_text"] in piece.body_text


def test_viewer_cannot_generate_and_member_cannot_read_other_store(client, db):
    lead_id = setup(client, db)
    from app.core.models import Operator

    operator = db.scalar(select(Operator).where(Operator.username == "tester"))
    operator.role = "viewer"
    db.commit()
    assert client.post(f"/api/leads/{lead_id}/sales-brief").status_code == 403
    operator.role = "member"
    db.commit()
    assert client.get(f"/api/leads/{lead_id}/sales-brief").status_code == 404
