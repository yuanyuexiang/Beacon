from datetime import UTC, datetime

from sqlalchemy import func, select

from app.modules.content.models import Approval, ContentPiece, ContentStatus
from app.modules.gmail import client as gmail_client
from app.modules.gmail.models import EmailDelivery
from app.modules.sales.models import ManualTask
from tests.test_communication import prepare
from tests.test_sales import _elig, _ready


def setup(client, db, monkeypatch, mode="gmail"):
    lead, _, original = _ready(client, db)
    _elig(client, lead)
    revised = client.post(
        f"/api/content/{original['id']}/revise", json={"body_text": original["body_text"], "subject": "Menu enquiry"}
    ).json()
    draft = prepare(client, lead, execution_mode=mode)["draft"]
    assert draft["content_id"] == revised["id"]
    calls = []

    def fake(method, path, payload=None):
        calls.append(path)
        if path == "/auth/status":
            return {"connected": True, "send_authorized": True, "email": "sender@example.org"}
        if path == "/policy":
            return {"sending_enabled": True, "queue_enabled": False}
        if path == "/preview":
            return {**payload, "approval_token": "mock-token", "expires_at": 4102444800}
        raise AssertionError(path)

    monkeypatch.setattr(gmail_client, "call", fake)
    return draft, calls


def test_preview_does_not_approve_or_create_and_confirm_is_idempotent(client, db, monkeypatch):
    draft, calls = setup(client, db, monkeypatch)
    base = f"/api/communication/drafts/{draft['id']}"
    preview = client.post(base + "/preview").json()
    assert preview["issues"] == []
    assert db.get(ContentPiece, draft["content_id"]).status == ContentStatus.draft
    assert not db.scalar(select(ManualTask.id))
    assert (
        client.post(base + "/confirm", json={"preview_hash": preview["preview_hash"], "confirmed": False}).status_code
        == 403
    )
    response = client.post(base + "/confirm", json={"preview_hash": preview["preview_hash"], "confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"
    assert db.scalar(select(EmailDelivery.status)) == "ready"
    again = client.post(base + "/confirm", json={"preview_hash": preview["preview_hash"], "confirmed": True})
    assert again.json()["task_id"] == response.json()["task_id"]
    assert db.scalar(select(func.count()).select_from(ManualTask)) == 1
    assert calls.count("/preview") == 1
    assert "/send" not in calls


def test_changed_recipient_or_message_invalidates_confirmation(client, db, monkeypatch):
    draft, _ = setup(client, db, monkeypatch)
    base = f"/api/communication/drafts/{draft['id']}"
    preview = client.post(base + "/preview").json()
    result = client.put(
        base + "/message",
        json={
            "content_id": draft["content_id"],
            "body_text": draft["context"]["contents"][0]["body_text"] + "\nThank you.",
            "subject": "Updated enquiry",
        },
    )
    assert result.status_code == 200, result.text
    assert (
        client.post(base + "/confirm", json={"preview_hash": preview["preview_hash"], "confirmed": True}).status_code
        == 409
    )
    assert not db.scalar(select(ManualTask.id))
    assert (
        client.put(
            base + "/message", json={"content_id": draft["content_id"], "body_text": "Stale edit", "subject": "Old"}
        ).status_code
        == 409
    )


def test_failed_preview_rolls_back_approval_and_task(client, db, monkeypatch):
    draft, _ = setup(client, db, monkeypatch)
    base = f"/api/communication/drafts/{draft['id']}"
    p = client.post(base + "/preview").json()
    original = gmail_client.call

    def fail(method, path, payload=None):
        if path == "/preview":
            raise gmail_client.GmailServiceError("offline")
        return original(method, path, payload)

    monkeypatch.setattr(gmail_client, "call", fail)
    before = db.scalar(select(func.count()).select_from(Approval))
    assert (
        client.post(base + "/confirm", json={"preview_hash": p["preview_hash"], "confirmed": True}).status_code == 409
    )
    assert not db.scalar(select(ManualTask.id))
    assert db.scalar(select(func.count()).select_from(Approval)) == before


def test_suppression_after_preview_stops_confirmation(client, db, monkeypatch):
    draft, _ = setup(client, db, monkeypatch, mode="manual")
    base = f"/api/communication/drafts/{draft['id']}"
    p = client.post(base + "/preview").json()
    from app.modules.sales.models import Suppression, SuppressionScope

    db.add(
        Suppression(
            lead_id=draft["lead_id"],
            scope=SuppressionScope.lead,
            reason="Customer declined",
            created_at=datetime.now(UTC),
            created_by="tester",
        )
    )
    db.commit()
    assert (
        client.post(base + "/confirm", json={"preview_hash": p["preview_hash"], "confirmed": True}).status_code == 409
    )
    assert not db.scalar(select(ManualTask.id))


def test_changed_sender_requires_new_preview(client, db, monkeypatch):
    draft, _ = setup(client, db, monkeypatch)
    base = f"/api/communication/drafts/{draft['id']}"
    p = client.post(base + "/preview").json()
    original = gmail_client.call

    def switched(method, path, payload=None):
        if path == "/auth/status":
            return {"connected": True, "send_authorized": True, "email": "different@example.org"}
        return original(method, path, payload)

    monkeypatch.setattr(gmail_client, "call", switched)
    response = client.post(base + "/confirm", json={"preview_hash": p["preview_hash"], "confirmed": True})
    assert response.status_code == 409
    assert not db.scalar(select(ManualTask.id))


def test_manual_confirmation_creates_record_without_delivery(client, db, monkeypatch):
    draft, calls = setup(client, db, monkeypatch, mode="manual")
    base = f"/api/communication/drafts/{draft['id']}"
    p = client.post(base + "/preview").json()
    response = client.post(base + "/confirm", json={"preview_hash": p["preview_hash"], "confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "manual"
    assert not db.scalar(select(EmailDelivery.id))
    assert calls == []


def test_email_unknown_evidence_can_be_explicitly_confirmed(client, db, monkeypatch):
    from app.modules.gmail import service as gmail_service
    from app.modules.sales.models import ChannelEligibility, Eligibility

    draft, calls = setup(client, db, monkeypatch)
    contact = db.get(ChannelEligibility, draft["eligibility_id"])
    contact.eligibility = Eligibility.unknown
    db.commit()
    base = f"/api/communication/drafts/{draft['id']}"
    p = client.post(base + "/preview").json()
    assert not p["issues"]
    assert contact.eligibility == Eligibility.unknown
    r = client.post(base + "/confirm", json={"preview_hash": p["preview_hash"], "confirmed": True})
    assert r.status_code == 200, r.text
    delivery = db.scalar(select(EmailDelivery))
    gmail_service.recheck(db, delivery)
    assert "/auth/status" in calls
    contact.contact_ref = "changed@example.org"
    db.commit()
    import pytest

    from app.modules.sales.service import SalesError

    with pytest.raises(SalesError):
        gmail_service.recheck(db, delivery)


def test_new_recipient_can_prepare_and_confirm_without_replacing_old_task(client, db, monkeypatch):
    draft, calls = setup(client, db, monkeypatch)
    base = f"/api/communication/drafts/{draft['id']}"
    first_preview = client.post(base + "/preview").json()
    first = client.post(base + "/confirm", json={"preview_hash": first_preview["preview_hash"], "confirmed": True})
    assert first.status_code == 200, first.text
    lead = draft["lead_id"]
    contact = _elig(client, lead, contact_ref="second@example.com").json()
    second = prepare(client, lead, execution_mode="gmail", eligibility_id=contact["id"])["draft"]
    assert second["id"] != draft["id"]
    assert second["eligibility_id"] == contact["id"]
    assert (
        prepare(client, lead, eligibility_id=draft["eligibility_id"])["existing_task"]["id"] == first.json()["task_id"]
    )
    base2 = f"/api/communication/drafts/{second['id']}"
    preview2 = client.post(base2 + "/preview").json()
    response = client.post(base2 + "/confirm", json={"preview_hash": preview2["preview_hash"], "confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["task_id"] != first.json()["task_id"]
    assert db.scalar(select(func.count()).select_from(ManualTask)) == 2
    assert "/send" not in calls
