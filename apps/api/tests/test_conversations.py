"""Conversation isolation, repeated sends and precise unread/reply association."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.modules.content import service as content
from app.modules.content.models import ContentPiece
from app.modules.sales.models import Channel, ChannelEligibility, Event, EventKind, ManualTask, TaskStatus
from tests.test_sales import _elig, _ready


def prepare_message(client, lead, contact):
    response = client.post(
        "/api/communication/prepare",
        json={
            "lead_ids": [lead],
            "channel": "email",
            "eligibility_id": str(contact),
            "purpose": "message",
            "execution_mode": "manual",
        },
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert not item.get("error"), item
    return item["draft"]


def write(client, draft, body="Hello, could you share your menu?", subject="Menu enquiry"):
    response = client.put(
        f"/api/communication/drafts/{draft['id']}/message",
        json={"content_id": draft["content_id"], "body_text": body, "subject": subject},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_same_channel_contacts_keep_independent_drafts_and_approvals(client, db):
    lead, _, _ = _ready(client, db)
    first = _elig(client, lead).json()
    second = ChannelEligibility(lead_id=lead, channel=Channel.email, contact_ref="second@example.org")
    db.add(second)
    db.commit()
    a = prepare_message(client, lead, first["id"])
    a = write(client, a, "Hello first recipient")
    b = write(client, prepare_message(client, lead, second.id), "Hello second recipient")
    assert a["id"] != b["id"]
    assert (
        client.patch(f"/api/communication/drafts/{a['id']}", json={"eligibility_id": str(second.id)}).status_code == 409
    )
    assert prepare_message(client, lead, first["id"])["content_id"] == a["content_id"]
    preview = client.post(f"/api/communication/drafts/{a['id']}/preview").json()
    assert preview["issues"] == [], preview
    confirmed = client.post(
        f"/api/communication/drafts/{a['id']}/confirm",
        json={"confirmed": True, "preview_hash": preview["preview_hash"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    piece = db.get(ContentPiece, a["content_id"])
    assert content.approval_valid(db, piece)[0]  # Another contact's newer content does not invalidate this send.
    assert b["content_id"] != a["content_id"]


def test_next_message_without_reply_preserves_history_and_confirmation_is_idempotent(client, db):
    lead, _, _ = _ready(client, db)
    contact = _elig(client, lead).json()
    a = write(client, prepare_message(client, lead, contact["id"]))
    url = f"/api/communication/drafts/{a['id']}"
    preview = client.post(url + "/preview").json()
    body = {"confirmed": True, "preview_hash": preview["preview_hash"]}
    one = client.post(url + "/confirm", json=body)
    assert one.status_code == 200, one.text
    assert client.post(url + "/confirm", json=body).json()["task_id"] == one.json()["task_id"]
    task = db.get(ManualTask, one.json()["task_id"])
    task.status, task.sent_at = TaskStatus.sent_manual, datetime.now(UTC)
    db.commit()
    b = write(client, prepare_message(client, lead, contact["id"]), "Hello, following up on my earlier note.")
    preview = client.post(f"/api/communication/drafts/{b['id']}/preview").json()
    assert not preview["issues"], preview
    two = client.post(
        f"/api/communication/drafts/{b['id']}/confirm",
        json={"confirmed": True, "preview_hash": preview["preview_hash"]},
    )
    assert two.status_code == 200, two.text
    messages = client.get(f"/api/communication/conversations/{lead}").json()["items"][0]["messages"]
    assert len(messages) == 2 and {m["body"] for m in messages} == {
        "Hello, could you share your menu?",
        "Hello, following up on my earlier note.",
    }


def test_unlinked_reply_and_arrival_watermark_and_manual_link(client, db):
    lead, _, _ = _ready(client, db)
    contact = _elig(client, lead).json()
    now = datetime.now(UTC)
    event = Event(
        lead_id=lead,
        channel=Channel.email,
        event_key="manual:unlinked",
        kind=EventKind.reply,
        recorded_at=now,
        occurred_at=now - timedelta(days=2),
        payload={"summary": "first"},
    )
    db.add(event)
    db.commit()
    url = f"/api/communication/conversations/{lead}"
    rows = client.get(url).json()["items"]
    unlinked = next(r for r in rows if r["id"] == "unlinked")
    assert unlinked["unread"] == 1
    assert client.put(url + "/unlinked/read", json={"through": unlinked["read_through"]}).status_code == 200
    later = Event(
        lead_id=lead,
        channel=Channel.email,
        event_key="manual:late",
        kind=EventKind.reply,
        recorded_at=now + timedelta(seconds=1),
        occurred_at=now - timedelta(days=3),
        payload={"summary": "late arrival"},
    )
    db.add(later)
    db.commit()
    assert next(r for r in client.get(url).json()["items"] if r["id"] == "unlinked")["unread"] == 1
    assert client.post(url + f"/events/{event.id}/link", json={"contact_id": contact["id"]}).status_code == 200
    rows = client.get(url).json()["items"]
    assert next(r for r in rows if r["id"] == contact["id"])["messages"][0]["body"] == "first"
    # Foreign contact cannot steal an incoming message.
    from tests.test_imports import upload

    upload(client, "b1", "fhrsid,name\n999,Another Store\n")
    other = next(r["id"] for r in client.get("/api/leads").json() if r["name"] == "Another Store")
    wrong = _elig(client, other).json()
    assert client.post(url + f"/events/{later.id}/link", json={"contact_id": wrong["id"]}).status_code == 422


def test_reply_is_scoped_to_contact_and_customer_list_orders_recent_activity(client, db):
    lead, _, _ = _ready(client, db)
    contact = _elig(client, lead).json()
    second = ChannelEligibility(lead_id=lead, channel=Channel.facebook, contact_ref="https://facebook.com/test")
    db.add(second)
    db.commit()
    a = write(client, prepare_message(client, lead, contact["id"]))
    task = ManualTask(
        lead_id=lead,
        channel=Channel.facebook,
        eligibility_id=second.id,
        content_id=a["content_id"],
        content_hash="test",
        status=TaskStatus.pending,
        created_by="tester",
        assigned_to="tester",
    )
    db.add(task)
    db.commit()
    response = client.post(
        f"/api/communication/conversations/{lead}/{contact['id']}/reply",
        json={"event_key": "manual:reply-one", "summary": "Yes, please send details"},
    )
    assert response.status_code == 200, response.text
    db.refresh(task)
    assert task.status == TaskStatus.pending
    rows = client.get("/api/communication/overview").json()["items"]
    assert rows[0]["id"] == lead and rows[0]["unread"] == 1
    assert rows[0]["last_message"] == "Yes, please send details"
    assert len(list(db.scalars(select(Event).where(Event.lead_id == lead)))) == 1


def test_ai_followup_only_receives_selected_contact_history(client, db, monkeypatch):
    from app.modules.content import outreach_ai
    from tests.test_outreach_ai import configure, request, result

    lead, _, _ = _ready(client, db)
    contact = _elig(client, lead).json()
    draft = prepare_message(client, lead, contact["id"])
    configure(client)
    now = datetime.now(UTC)
    db.add_all(
        [
            Event(
                lead_id=lead,
                channel=Channel.email,
                event_key="manual:bound",
                kind=EventKind.reply,
                recorded_at=now,
                payload={"summary": "Please quote 100 menus", "eligibility_id": contact["id"]},
            ),
            Event(
                lead_id=lead,
                channel=Channel.facebook,
                event_key="manual:other-platform",
                kind=EventKind.reply,
                recorded_at=now,
                payload={"summary": "Other platform private reply"},
            ),
        ]
    )
    db.commit()
    captured = []

    def generate(task):
        captured.append(task)
        return result()

    monkeypatch.setattr(outreach_ai, "generate", generate)
    response = request(
        client, lead, eligibility_id=contact["id"], conversation_draft_id=draft["id"], writing_action="reply"
    )
    assert response.status_code == 201, response.text
    assert captured[0]["writing_action"] == "reply"
    history = next(s["text"] for s in captured[0]["sources"] if s["id"] == "conversation")
    assert "Please quote 100 menus" in history
    assert "Other platform private reply" not in history


def test_conversation_permissions_and_read_positions_are_per_operator(client, db):
    from tests.test_assignment import assign, person
    from tests.test_users import session

    lead, _, _ = _ready(client, db)
    contact = _elig(client, lead).json()
    alice = session(person(db, "conversation-alice", "member"))
    bob = session(person(db, "conversation-bob", "member"))
    assert assign(client, lead, "conversation-alice").status_code == 200
    url = f"/api/communication/conversations/{lead}"
    assert bob.get(url).status_code == 404
    assert bob.post(url + f"/{contact['id']}/reply", json={"event_key": "blocked", "summary": "no"}).status_code == 404
    assert (
        alice.post(url + f"/{contact['id']}/reply", json={"event_key": "manual:alice", "summary": "Hello"}).status_code
        == 200
    )
    row = next(r for r in alice.get(url).json()["items"] if r["id"] == contact["id"])
    assert row["unread"] == 1
    assert alice.put(url + f"/{contact['id']}/read", json={"through": row["read_through"]}).status_code == 200
    assert next(r for r in alice.get(url).json()["items"] if r["id"] == contact["id"])["unread"] == 0
    assert next(r for r in client.get(url).json()["items"] if r["id"] == contact["id"])["unread"] == 1
