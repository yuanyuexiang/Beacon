import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.outreach import client as provider
from app.modules.outreach import service
from app.modules.outreach.models import ChannelAccount, Conversation, ConversationEvent, OutreachDelivery
from app.modules.sales.models import Event, ManualTask
from tests.test_sales import _elig, _ready


@pytest.fixture
def setup(client, db, monkeypatch):
    lead_id, _, content = _ready(client, db)
    elig = _elig(client, lead_id, channel="facebook", contact_ref="https://facebook.com/restaurant").json()
    a = ChannelAccount(
        platform="facebook",
        label="Our page",
        auth_mode="facebook_login",
        sender_id="1234",
        connected=True,
        auth_version="v1",
        sending_enabled=True,
        queue_enabled=True,
        capabilities=["text_reply"],
        daily_limit=20,
    )
    db.add(a)
    db.flush()
    c = Conversation(
        account_id=a.id,
        recipient_id="999",
        lead_id=uuid.UUID(lead_id),
        eligibility_id=uuid.UUID(elig["id"]),
        mapping_version="map1",
        last_inbound_at=service.now(),
    )
    db.add(c)
    db.commit()
    task = client.post(
        f"/api/leads/{lead_id}/tasks", json={"eligibility_id": elig["id"], "content_id": content["id"]}
    ).json()
    calls = []
    state = {"verified": True, "version": "v1", "sending_enabled": True, "capabilities": ["text_reply"]}

    def call(method, path, body=None):
        calls.append((method, path, body))
        if path == f"/accounts/{a.id}":
            return state.copy()
        if path == "/preview":
            return {
                **body,
                "version": state["version"],
                "expires_at": int(time.time()) + 1800,
                "approval_token": "server-only",
            }
        if path == "/send":
            return {"status": "sent", "message_id": "meta.message.1"}
        if path.startswith("/requests/"):
            return {"status": "unknown"}
        if path == "/webhook/verify":
            return {"events": []}
        raise AssertionError(path)

    monkeypatch.setattr(provider, "call", call)
    return task, a, c, calls, state


def preview(client, task, c):
    result = client.post("/api/outreach/preview", json={"task_id": task["id"], "conversation_id": str(c.id)})
    assert result.status_code == 200, result.text
    return result.json()


def approve(client, d, **kwargs):
    return client.post(
        "/api/outreach/approve",
        json={"delivery_ids": [d["id"]], "preview_keys": {d["id"]: d["preview_key"]}, "confirmed": True, **kwargs},
    )


def test_approved_send_once_and_manual_guard(client, db, setup):
    task, a, c, calls, _ = setup
    d = preview(client, task, c)
    assert d["payload"]["recipient_id"] == "999" and "approval_token" not in d
    assert not any(path == "/send" for _, path, _ in calls)
    assert approve(client, d).status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/open").status_code == 409
    service.tick(db)
    service.tick(db)
    assert db.get(ManualTask, uuid.UUID(task["id"])).status.value == "sent_social"
    assert sum(path == "/send" for _, path, _ in calls) == 1
    assert client.get("/api/outreach/deliveries").json()[0]["platform_message_id"] == "meta.message.1"


@pytest.mark.parametrize(
    "change", ["expired", "wrong_lead", "wrong_eligibility", "wrong_account", "paused", "auth_version", "disabled"]
)
def test_execution_rechecks_conditions(client, db, setup, change):
    task, a, c, calls, state = setup
    d = preview(client, task, c)
    assert approve(client, d).status_code == 200
    row = db.get(OutreachDelivery, uuid.UUID(d["id"]))
    if change == "expired":
        c.last_inbound_at = service.now() - timedelta(days=2)
    elif change == "wrong_lead":
        c.lead_id = None
    elif change == "wrong_eligibility":
        c.eligibility_id = None
    elif change == "wrong_account":
        row.mapping_version = "changed"
    elif change == "paused":
        db.get(ManualTask, uuid.UUID(task["id"])).status = "paused"
    elif change == "auth_version":
        state["version"] = "new"
    else:
        state["sending_enabled"] = False
    db.commit()
    service.tick(db)
    db.refresh(row)
    assert row.status == "blocked"
    assert not any(path == "/send" for _, path, _ in calls)


def test_unknown_not_retried_and_query_only(client, db, setup, monkeypatch):
    task, a, c, calls, _ = setup
    original = provider.call

    def uncertain(method, path, body=None):
        if path == "/send":
            calls.append((method, path, body))
            raise provider.ProviderError("network unavailable")
        return original(method, path, body)

    monkeypatch.setattr(provider, "call", uncertain)
    d = preview(client, task, c)
    assert approve(client, d).status_code == 200
    service.tick(db)
    service.tick(db)
    assert client.post(f"/api/outreach/deliveries/{d['id']}/reconcile").json()["status"] == "unknown"
    assert (
        client.post("/api/outreach/preview", json={"task_id": task["id"], "conversation_id": str(c.id)}).status_code
        == 409
    )
    assert sum(path == "/send" for _, path, _ in calls) == 1


def test_queue_pause_and_stale_preview(client, db, setup):
    task, a, c, calls, _ = setup
    old = preview(client, task, c)
    latest = preview(client, task, c)
    assert approve(client, old).status_code == 409
    assert approve(client, latest, queued=True).status_code == 200
    a.queue_enabled = False
    db.commit()
    service.tick(db)
    assert not any(path == "/send" for _, path, _ in calls)
    a.queue_enabled = True
    db.commit()
    service.tick(db)
    assert sum(path == "/send" for _, path, _ in calls) == 1


def test_events_dedupe_scope_and_reply_pause(client, db, setup):
    task, a, c, calls, _ = setup
    event = {
        "platform": "facebook",
        "sender_id": a.sender_id,
        "recipient_id": c.recipient_id,
        "message_id": "inbound.1",
        "occurred_at": service.now().timestamp(),
        "text": "hello",
    }
    assert service.ingest(db, [event, event]) == 1
    assert service.ingest(db, [event]) == 0
    service.process_events(db)
    service.process_events(db)
    assert db.get(ManualTask, uuid.UUID(task["id"])).status.value == "paused"
    assert len(list(db.scalars(select(Event)))) == 1
    newest = c.last_inbound_at
    event.update(message_id="older.1", occurred_at=(service.now() - timedelta(days=3)).timestamp())
    service.ingest(db, [event])
    db.refresh(c)
    assert c.last_inbound_at == newest
    event.update(sender_id="other-account", message_id="foreign.1")
    assert service.ingest(db, [event]) == 0


def test_unmapped_conversation_waits_for_binding(client, db, setup):
    task, a, c, _, _ = setup
    event = {
        "platform": "facebook",
        "sender_id": a.sender_id,
        "recipient_id": "888",
        "message_id": "unmapped.1",
        "occurred_at": service.now().timestamp(),
        "text": "unknown",
    }
    service.ingest(db, [event])
    service.process_events(db)
    ev = db.scalar(select(ConversationEvent).where(ConversationEvent.message_id == "unmapped.1"))
    assert not ev.processed
    conversation = db.get(Conversation, ev.conversation_id)
    assert conversation.lead_id is None
    service.bind(db, conversation, c.eligibility_id)
    db.refresh(ev)
    assert ev.processed
    assert db.get(ManualTask, uuid.UUID(task["id"])).status.value == "paused"


def test_config_defaults_and_secret_validation(client, db):
    _ready(client, db)
    r = client.post(
        "/api/outreach/accounts",
        json={"platform": "facebook", "label": "Test page", "auth_mode": "facebook_login", "sender_id": "1234"},
    )
    assert r.status_code == 200
    a = r.json()
    assert not a["connected"] and not a["sending_enabled"] and not a["queue_enabled"]
    r = client.put("/api/outreach/app", json={"app_secret": "do-not-echo"})
    assert r.status_code == 422 and "do-not-echo" not in r.text


def test_webhook_unavailable_returns_non_success(client, db, setup, monkeypatch):
    def unavailable(*_):
        raise provider.ProviderError("offline")

    monkeypatch.setattr(provider, "call", unavailable)
    assert (
        client.post("/api/outreach/webhook", content=b"{}", headers={"x-hub-signature-256": "bad"}).status_code == 503
    )


def test_batch_approval_is_atomic(client, db, setup):
    task, a, c, _, _ = setup
    d = preview(client, task, c)
    result = client.post(
        "/api/outreach/approve",
        json={
            "delivery_ids": [d["id"], str(uuid.uuid4())],
            "preview_keys": {d["id"]: d["preview_key"]},
            "confirmed": True,
            "queued": True,
        },
    )
    assert result.status_code == 409
    db.expire_all()
    assert db.get(OutreachDelivery, uuid.UUID(d["id"])).status == "preview"


def test_provider_pre_submit_rejection_is_blocked_not_unknown(client, db, setup, monkeypatch):
    task, a, c, _, _ = setup
    original = provider.call

    def rejected(method, path, body=None):
        if path == "/send":
            raise provider.ProviderError("发送已暂停", status_code=409)
        return original(method, path, body)

    monkeypatch.setattr(provider, "call", rejected)
    d = preview(client, task, c)
    assert approve(client, d).status_code == 200
    service.tick(db)
    db.expire_all()
    assert db.get(OutreachDelivery, uuid.UUID(d["id"])).status == "blocked"
