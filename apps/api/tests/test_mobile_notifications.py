"""Phone notification simulations; no real private notifications or external sends."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.models import Operator
from app.modules.mobile.models import Device, Execution, ReplyNotification, ReplyThread
from app.modules.mobile.routes import digest
from app.modules.sales import service
from app.modules.sales.models import Event, EventKind, ManualTask
from tests.test_mobile import enqueue, setup


def prepared(client, db):
    tid, device, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, device)
    j = db.get(Execution, uuid.UUID(job["id"]))
    j.status, j.started_at = "sent", service.now()
    db.commit()
    return tid, job, headers


def notice(index=1, **changes):
    return {
        "event_key": digest(f"notice-{index}"),
        "channel": "whatsapp",
        "thread_key": digest("thread-1"),
        "title": "Test Cafe",
        "body": f"Please send details {index}",
        "occurred_at": service.now().isoformat(),
        "structured": True,
        **changes,
    }


def push(client, headers, body):
    r = client.post("/api/mobile/device/notifications", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_first_notice_requires_link_then_same_stable_thread_automatically_records(client, db):
    tid, job, headers = prepared(client, db)
    first = push(client, headers, notice())
    assert first["status"] == "pending"
    assert not db.scalar(select(Event).where(Event.kind == EventKind.reply))
    url = f"/api/mobile/notifications/{first['id']}/link"
    args = {"execution_id": job["id"], "remember": True}
    for _ in range(2):
        assert client.post(url, json=args).status_code == 200
    assert len(list(db.scalars(select(Event).where(Event.kind == EventKind.reply)))) == 1
    second_body = notice(2)
    second = push(client, headers, second_body)
    assert second["status"] == "linked"
    assert push(client, headers, second_body)["created"] is False
    linked = client.get("/api/mobile/notifications?status=linked").json()
    assert len(linked) == 2 and linked[0]["read"] is False
    assert client.post(f"/api/mobile/notifications/{second['id']}/read").status_code == 200
    db.expire_all()
    assert db.get(ManualTask, uuid.UUID(tid)).status.value == "paused"
    events = list(db.scalars(select(Event).where(Event.kind == EventKind.reply)))
    assert len(events) == 2 and any(e.payload.get("automatic") for e in events)


def test_names_never_auto_match_and_unstructured_messages_stay_pending(client, db):
    _, job, headers = prepared(client, db)
    first = push(client, headers, notice())
    client.post(f"/api/mobile/notifications/{first['id']}/link", json={"execution_id": job["id"]})
    assert push(client, headers, notice(2, thread_key=None))["status"] == "pending"
    assert push(client, headers, notice(3, structured=False))["status"] == "pending"
    assert push(client, headers, notice(4, thread_key=digest("different")))["status"] == "pending"
    assert client.post("/api/mobile/notification-threads/reset").status_code == 200
    assert push(client, headers, notice(5))["status"] == "pending"


def test_handoff_self_message_and_channel_mismatch_do_not_auto_fill(client, db):
    tid, job, headers = prepared(client, db)
    first = push(client, headers, notice())
    args = {"execution_id": job["id"]}
    client.post(f"/api/mobile/notifications/{first['id']}/link", json=args)
    j = db.get(Execution, uuid.UUID(job["id"]))
    assert push(client, headers, notice(2, body=j.snapshot["body"]))["status"] == "pending"
    wrong = push(client, headers, notice(3, channel="facebook"))
    assert client.post(f"/api/mobile/notifications/{wrong['id']}/link", json=args).status_code == 409
    t = db.get(ManualTask, uuid.UUID(tid))
    db.add(Operator(username="another-member", password_hash="test-only", role="member", is_active=True))
    db.flush()
    t.assigned_to = "another-member"
    db.commit()
    assert push(client, headers, notice(4))["status"] == "pending"
    assert not client.get("/api/mobile/reply-targets").json()


def test_device_and_operator_isolation_revocation_and_retention(client, db):
    _, job, headers = prepared(client, db)
    first = push(client, headers, notice())
    device = db.get(Device, db.get(Execution, uuid.UUID(job["id"])).device_id)
    original_owner = device.owner
    db.add(Operator(username="other-owner", password_hash="test-only", role="member", is_active=True))
    db.flush()
    device.owner = "other-owner"
    db.commit()
    assert client.get("/api/mobile/notifications").json() == []
    assert client.post(f"/api/mobile/notifications/{first['id']}/ignore").status_code == 404
    device.owner = original_owner
    db.commit()
    assert client.post(f"/api/mobile/notifications/{first['id']}/ignore").status_code == 200
    assert client.get("/api/mobile/notifications?status=ignored").json()[0]["body"] == "（已忽略）"
    stale = push(client, headers, notice(2))
    row = db.get(ReplyNotification, uuid.UUID(stale["id"]))
    row.created_at = service.now() - timedelta(days=8)
    db.commit()
    assert client.get("/api/mobile/notifications").json() == []
    device.status = "revoked"
    db.commit()
    assert client.post("/api/mobile/device/notifications", headers=headers, json=notice(3)).status_code == 401


def test_invalid_notifications_and_explicit_no_remember(client, db):
    _, job, headers = prepared(client, db)
    assert (
        client.post("/api/mobile/device/notifications", headers=headers, json=notice(channel="email")).status_code
        == 422
    )
    assert client.post("/api/mobile/device/notifications", headers=headers, json=notice(body=" ")).status_code == 422
    assert (
        client.post(
            "/api/mobile/device/notifications",
            headers=headers,
            json=notice(occurred_at=(service.now() - timedelta(days=8)).isoformat()),
        ).status_code
        == 422
    )
    first = push(client, headers, notice())
    assert (
        client.post(
            f"/api/mobile/notifications/{first['id']}/link", json={"execution_id": job["id"], "remember": False}
        ).status_code
        == 200
    )
    assert not db.scalar(select(ReplyThread))
    assert push(client, headers, notice(2))["status"] == "pending"


def test_foreground_reply_binds_execution_and_deduplicates_notification(client, db):
    _, job, headers = prepared(client, db)
    j = db.get(Execution, uuid.UUID(job["id"]))
    body = notice(source="foreground", execution_id=job["id"], verified_target=j.snapshot["target"])
    first = push(client, headers, body)
    assert first["status"] == "linked"
    assert push(client, headers, body)["created"] is False
    event = db.scalar(select(Event).where(Event.kind == EventKind.reply))
    assert event.payload["source"] == "mobile_foreground"
    assert event.payload["time_basis"] == "observed"
    incoming = push(client, headers, notice(2, body=body["body"]))
    assert (
        client.post(f"/api/mobile/notifications/{incoming['id']}/link", json={"execution_id": job["id"]}).status_code
        == 200
    )
    assert len(list(db.scalars(select(Event).where(Event.kind == EventKind.reply)))) == 1


def test_foreground_reply_rejects_wrong_target_outgoing_and_handoff(client, db):
    tid, job, headers = prepared(client, db)
    j = db.get(Execution, uuid.UUID(job["id"]))
    body = notice(source="foreground", execution_id=job["id"], verified_target=j.snapshot["target"])
    for change in [
        {"verified_target": "https://wrong.example"},
        {"channel": "facebook"},
        {"body": j.snapshot["body"]},
        {"structured": False},
        {"execution_id": str(uuid.uuid4())},
    ]:
        assert (
            client.post("/api/mobile/device/notifications", headers=headers, json={**body, **change}).status_code == 409
        )
    db.add(Operator(username="different-owner", password_hash="test-only", role="member", is_active=True))
    db.flush()
    db.get(ManualTask, uuid.UUID(tid)).assigned_to = "different-owner"
    db.commit()
    assert client.post("/api/mobile/device/notifications", headers=headers, json=body).status_code == 409
    assert not db.scalar(select(Event).where(Event.kind == EventKind.reply))


def test_admin_phone_reply_uses_same_delegation_rule_as_sending(client, db):
    tid, job, headers = prepared(client, db)
    j = db.get(Execution, uuid.UUID(job["id"]))
    db.add(Operator(username="sales-reply-owner", password_hash="test-only", role="member", is_active=True))
    db.flush()
    db.get(ManualTask, uuid.UUID(tid)).assigned_to = "sales-reply-owner"
    j.snapshot = {**j.snapshot, "task_owner": "sales-reply-owner"}
    db.commit()
    body = notice(source="foreground", execution_id=job["id"], verified_target=j.snapshot["target"])
    assert push(client, headers, body)["status"] == "linked"
    db.get(ManualTask, uuid.UUID(tid)).assigned_to = "tester"
    db.commit()
    assert (
        client.post(
            "/api/mobile/device/notifications", headers=headers, json={**body, "event_key": digest("after-transfer")}
        ).status_code
        == 409
    )
