import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.gmail import client as gmail_client
from app.modules.gmail import service
from app.modules.gmail.models import EmailDelivery
from app.modules.sales.models import Event, ManualTask
from tests.test_sales import _elig, _ready


@pytest.fixture
def setup(client, db, monkeypatch):
    lead_id, _, content = _ready(client, db)
    elig = _elig(client, lead_id).json()
    task = client.post(
        f"/api/leads/{lead_id}/tasks", json={"eligibility_id": elig["id"], "content_id": content["id"]}
    ).json()
    calls = []
    policy = {"sending_enabled": True, "queue_enabled": True, "daily_limit": 0}

    def fake_call(method, path, body=None):
        calls.append((method, path, body))
        if path == "/policy":
            return policy.copy()
        if path == "/preview":
            return {**body, "approval_token": "fake-preview-token", "expires_at": int(time.time()) + 1800}
        if path == "/send":
            return {"status": "sent", "id": "qa-message", "threadId": "qa-thread", "sent_at": int(time.time())}
        if path.startswith("/requests/"):
            return {"status": "unknown"}
        if path == "/replies":
            return {
                "results": [
                    {
                        "sent_message_id": "qa-message",
                        "threadId": "qa-thread",
                        "replies": [{"id": "qa-reply", "from": "customer@example.com", "subject": "Reply"}],
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(gmail_client, "call", fake_call)
    return task, calls, policy


def preview(client, task):
    response = client.post("/api/gmail/preview", json={"task_ids": [task["id"]], "subject": "Personal menu idea"})
    assert response.status_code == 200, response.text
    return response.json()[0]


def approve(client, delivery, queued=False):
    return client.post(
        "/api/gmail/approve",
        json={
            "delivery_ids": [delivery["id"]],
            "preview_keys": {delivery["id"]: delivery["preview_key"]},
            "confirmed": True,
            "queued": queued,
        },
    )


def test_preview_requires_confirmation_and_worker_sends_once(client, db, setup):
    task, calls, _ = setup
    delivery = preview(client, task)
    assert delivery["payload"]["to"] == ["info@example.com"]
    assert "approval_token" not in delivery
    assert not any(path == "/send" for _, path, _ in calls)
    denied = client.post("/api/gmail/approve", json={"delivery_ids": [delivery["id"]], "confirmed": False})
    assert denied.status_code == 400
    assert approve(client, delivery).status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/open").status_code == 409
    service.tick(db)
    assert db.get(ManualTask, uuid.UUID(task["id"])).status.value == "sent_email"
    assert client.get("/api/gmail/deliveries").json()[0]["gmail_message_id"] == "qa-message"
    service.tick(db)
    assert sum(path == "/send" for _, path, _ in calls) == 1
    assert client.post(f"/api/tasks/{task['id']}/cancel", json={"reason": "x"}).status_code == 409


@pytest.mark.parametrize("event", ["reply", "reject", "unsubscribe", "bounce"])
def test_queue_rechecks_events_before_send(client, db, setup, event):
    task, calls, _ = setup
    delivery = preview(client, task)
    assert approve(client, delivery, queued=True).status_code == 200
    client.post(
        f"/api/leads/{task['lead_id']}/events", json={"event_key": "qa-block", "kind": event, "channel": "email"}
    )
    service.tick(db)
    assert not any(path == "/send" for _, path, _ in calls)
    assert db.get(EmailDelivery, uuid.UUID(delivery["id"])).status == "blocked"


def test_queue_paused_expiry_cancel_and_recipient_change(client, db, setup):
    task, calls, policy = setup
    delivery = preview(client, task)
    approve(client, delivery, queued=True)
    policy["queue_enabled"] = False
    service.tick(db)
    assert not any(path == "/send" for _, path, _ in calls)
    assert client.post(f"/api/gmail/deliveries/{delivery['id']}/cancel").status_code == 200
    delivery = preview(client, task)
    row = db.get(EmailDelivery, uuid.UUID(delivery["id"]))
    row.expires_at = service.now() - timedelta(seconds=1)
    db.commit()
    assert approve(client, delivery).status_code == 409
    delivery = preview(client, task)
    from app.modules.sales.models import ChannelEligibility

    elig = db.get(ChannelEligibility, uuid.UUID(task["eligibility_id"]))
    elig.contact_ref = "new@example.com"
    db.commit()
    assert approve(client, delivery).status_code == 409


def test_network_unknown_not_retried_and_can_reconcile(client, db, setup, monkeypatch):
    task, calls, _ = setup
    delivery = preview(client, task)
    approve(client, delivery)
    old = gmail_client.call

    def interrupted(method, path, body=None):
        if path == "/send":
            raise gmail_client.GmailServiceError("timeout")
        return old(method, path, body)

    monkeypatch.setattr(gmail_client, "call", interrupted)
    service.tick(db)
    row = db.get(EmailDelivery, uuid.UUID(delivery["id"]))
    assert row.status == "unknown"
    assert client.post("/api/gmail/preview", json={"task_ids": [task["id"]], "subject": "Retry"}).status_code == 409
    service.tick(db)

    def recovered(method, path, body=None):
        if path.startswith("/requests/"):
            return {"status": "sent", "id": "late-id", "threadId": "late-thread", "sent_at": int(time.time())}
        return old(method, path, body)

    monkeypatch.setattr(gmail_client, "call", recovered)
    result = client.post(f"/api/gmail/deliveries/{delivery['id']}/reconcile")
    assert result.json()["gmail_message_id"] == "late-id"


def test_reply_sync_is_idempotent_and_pauses_followup(client, db, setup):
    task, _, _ = setup
    delivery = preview(client, task)
    approve(client, delivery)
    service.tick(db)
    # 复用已审批内容创建后续任务，模拟收到回复时已有待处理跟进。
    followup = client.post(
        f"/api/leads/{task['lead_id']}/tasks",
        json={"eligibility_id": task["eligibility_id"], "content_id": task["content_id"]},
    ).json()
    assert client.post("/api/gmail/sync-replies").json()["replies"] == 1
    assert client.post("/api/gmail/sync-replies").json()["replies"] == 0
    assert db.get(ManualTask, uuid.UUID(followup["id"])).status.value == "paused"
    events = list(db.scalars(select(Event)))
    assert len(events) == 1 and events[0].event_key == "gmail:qa-reply"


def test_no_login_cannot_manage_gmail(client, db, setup):
    client.cookies.clear()
    assert client.get("/api/gmail/status").status_code == 401
    assert client.post("/api/gmail/credentials", json={"credentials": {}}).status_code == 401


def test_old_preview_cannot_confirm_replaced_content(client, db, setup):
    task, calls, _ = setup
    original = preview(client, task)
    replacement = client.post(
        "/api/gmail/preview", json={"task_ids": [task["id"]], "subject": "Changed subject"}
    ).json()[0]
    assert replacement["id"] == original["id"] and replacement["preview_key"] != original["preview_key"]
    assert approve(client, original).status_code == 409
    assert approve(client, replacement).status_code == 200
    service.tick(db)
    assert next(body for _, path, body in calls if path == "/send")["subject"] == "Changed subject"


def test_batch_confirmation_is_atomic_and_queue_can_pause(client, db, setup):
    task, calls, policy = setup
    elig = _elig(client, task["lead_id"], contact_ref="second@example.com").json()
    other = client.post(
        f"/api/leads/{task['lead_id']}/tasks", json={"eligibility_id": elig["id"], "content_id": task["content_id"]}
    ).json()
    response = client.post(
        "/api/gmail/preview", json={"task_ids": [task["id"], other["id"]], "subject": "Batch preview"}
    )
    assert response.status_code == 200
    deliveries = response.json()
    assert len(deliveries) == 2 and deliveries[0]["batch_key"] == deliveries[1]["batch_key"]
    keys = {row["id"]: row["preview_key"] for row in deliveries}
    keys[deliveries[0]["id"]] = "old-preview"
    response = client.post(
        "/api/gmail/approve",
        json={
            "delivery_ids": [row["id"] for row in deliveries],
            "preview_keys": keys,
            "confirmed": True,
            "queued": True,
        },
    )
    assert response.status_code == 409
    assert all(row.status == "preview" for row in db.scalars(select(EmailDelivery)))
    keys = {row["id"]: row["preview_key"] for row in deliveries}
    response = client.post(
        "/api/gmail/approve",
        json={
            "delivery_ids": [row["id"] for row in deliveries],
            "preview_keys": keys,
            "confirmed": True,
            "queued": True,
        },
    )
    assert response.status_code == 200
    policy["sending_enabled"] = False
    service.tick(db)
    assert not any(path == "/send" for _, path, _ in calls)
    policy["sending_enabled"] = True
    service.tick(db)
    service.tick(db)
    assert sum(path == "/send" for _, path, _ in calls) == 2
    assert all(len(body["to"]) == 1 for _, path, body in calls if path == "/send")


def test_oauth_callback_log_does_not_include_authorization_code():
    import logging

    from app.main import OAuthAccessFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/api/gmail/oauth/callback?code=private-code&state=private-state", "1.1", 303),
        None,
    )
    OAuthAccessFilter().filter(record)
    assert "private-code" not in record.getMessage() and "private-state" not in record.getMessage()


@pytest.mark.parametrize("change", ["disabled", "viewer", "password_reset"])
def test_queue_rechecks_operator_permission_before_submission(client, db, setup, change):
    from app.core.models import Operator

    task, calls, _ = setup
    delivery = preview(client, task)
    assert approve(client, delivery, queued=True).status_code == 200
    op = db.scalar(select(Operator).where(Operator.username == "tester"))
    if change == "disabled":
        op.is_active = False
    elif change == "viewer":
        op.role = "viewer"
    else:
        op.must_change_password = True
    db.commit()
    service.tick(db)
    row = db.get(EmailDelivery, uuid.UUID(delivery["id"]))
    assert row.status == "blocked" and "发送权限" in row.last_error
    assert not any(path == "/send" for _, path, _ in calls)
