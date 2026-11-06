"""Multi-channel phone contracts are simulated; these tests never open or message real accounts."""

import pytest

from app.modules.mobile.channels import destination
from app.modules.sales.models import Event, ManualTask, TaskStatus
from tests.test_mobile import enqueue, setup
from tests.test_sales import _elig


@pytest.mark.parametrize(
    "channel,value,platform",
    [
        ("facebook", "http://www.facebook.com/profile.php?id=123&ref=test", "facebook"),
        ("instagram", "https://instagram.com/test.restaurant/", "instagram"),
        ("linkedin", "https://www.linkedin.com/in/test-person", "linkedin"),
        ("tiktok", "https://tiktok.com/@test.restaurant", "tiktok"),
        ("other_social", "https://youtube.com/@test.restaurant", "youtube"),
        ("other_social", "https://x.com/test_restaurant", "x"),
    ],
)
def test_canonical_platform_destinations(channel, value, platform):
    resolved, target = destination(channel, value)
    assert resolved == platform and target.startswith("https://")
    assert "ref=" not in target


@pytest.mark.parametrize(
    "value",
    [
        "https://instagram.com.evil.test/shop",
        "https://user:pass@instagram.com/shop",
        "https://instagram.com/p/123",
        "https://youtube.com/watch?v=123",
        "https://youtu.be/abc",
        "https://linkedin.com/posts/test",
        "file:///tmp/a",
        "https://x.com/intent",
    ],
)
def test_non_profile_and_mismatched_destinations_rejected(value):
    with pytest.raises(ValueError):
        destination("other_social", value)
    with pytest.raises(ValueError):
        destination("email", value)


def social_task(client, db):
    tid, device, headers, _ = setup(client, db)
    original = db.get(ManualTask, tid)
    e = _elig(client, str(original.lead_id), channel="instagram", contact_ref="https://instagram.com/test_shop").json()
    made = client.post(
        f"/api/leads/{original.lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": str(original.content_id)}
    )
    assert made.status_code == 201, made.text
    body = {
        "protocol": 2,
        "account": "+447700900001",
        "accounts": {"whatsapp": "+447700900001", "instagram": "@our_shop"},
        "installed": ["whatsapp", "instagram"],
        "ready": True,
        "accessibility": True,
        "app_version": "test",
    }
    assert client.post("/api/mobile/device/heartbeat", headers=headers, json=body).status_code == 200
    return made.json()["id"], device, headers, body


def test_social_action_confirmation_is_immutable_and_account_change_cancels(client, db):
    tid, device, headers, heartbeat = social_task(client, db)
    args = {"device_id": device["device_id"], "preview_hash": "0" * 64, "action": "message_request"}
    url = f"/api/mobile/tasks/{tid}"
    preview = client.post(url + "/preview", json=args)
    assert preview.status_code == 200, preview.text
    view = preview.json()
    assert view["payload"]["channel"] == "instagram" and view["payload"]["sender"] == "@our_shop"
    assert view["payload"]["action"] == "message_request"
    assert (
        client.post(
            url + "/confirm", json={**args, "preview_hash": view["preview_hash"], "action": "direct_message"}
        ).status_code
        == 409
    )
    assert client.post(url + "/confirm", json={**args, "preview_hash": view["preview_hash"]}).status_code == 200
    heartbeat["accounts"]["instagram"] = "@another_shop"
    client.post("/api/mobile/device/heartbeat", headers=headers, json=heartbeat)
    assert client.get(url).json()["status"] == "cancelled"


def test_social_needs_action_and_reply_dedup_do_not_claim_sent(client, db):
    tid, device, headers, _ = social_task(client, db)
    job, _ = enqueue(client, tid, device)
    claim = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    assert claim["id"] == job["id"]
    base = f"/api/mobile/device/jobs/{job['id']}"
    attempt = {"lease": claim["lease"], "attempt": claim["attempt"]}
    r = client.post(
        base + "/result", headers=headers, json={**attempt, "status": "needs_action", "detail": "No message entry"}
    )
    assert r.status_code == 200 and r.json()["status"] == "needs_action"
    db.expire_all()
    assert db.get(ManualTask, tid).status == TaskStatus.pending
    assert (
        client.post(
            base + "/inbound",
            headers=headers,
            json={"body": "Thanks, can you send a quote?", "confirmed_incoming": True},
        ).json()["created"]
        is True
    )
    duplicate = client.post(
        base + "/inbound", headers=headers, json={"body": "Thanks, can you send a quote?", "confirmed_incoming": True}
    )
    assert duplicate.status_code == 200 and duplicate.json()["created"] is False
    assert db.query(Event).count() == 1
    db.expire_all()
    assert db.get(ManualTask, tid).status == TaskStatus.paused


def test_missing_platform_account_or_app_is_explicit(client, db):
    tid, device, headers, heartbeat = social_task(client, db)
    heartbeat["installed"] = ["whatsapp"]
    client.post("/api/mobile/device/heartbeat", headers=headers, json=heartbeat)
    r = client.post(
        f"/api/mobile/tasks/{tid}/preview", json={"device_id": device["device_id"], "preview_hash": "0" * 64}
    )
    assert r.status_code == 409 and "安装" in r.json()["detail"]


def test_request_submission_is_not_sent_and_activity_keeps_platform(client, db):
    tid, device, headers, _ = social_task(client, db)
    args = {"device_id": device["device_id"], "preview_hash": "0" * 64, "action": "message_request"}
    url = f"/api/mobile/tasks/{tid}"
    args["preview_hash"] = client.post(url + "/preview", json=args).json()["preview_hash"]
    job = client.post(url + "/confirm", json=args).json()
    claim = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    base = f"/api/mobile/device/jobs/{job['id']}"
    attempt = {"lease": claim["lease"], "attempt": claim["attempt"]}
    assert (
        client.post(base + "/result", headers=headers, json={**attempt, "status": "request_submitted"}).status_code
        == 409
    )
    assert client.post(base + "/start", headers=headers, json=attempt).status_code == 200
    assert (
        client.post(base + "/result", headers=headers, json={**attempt, "status": "request_submitted"}).status_code
        == 200
    )
    db.expire_all()
    task = db.get(ManualTask, tid)
    assert task.status == TaskStatus.pending and task.sent_at is None
    progress = client.get(f"/api/communication/leads/{task.lead_id}").json()
    assert progress["progress"]["status"] == "waiting_acceptance"
    assert client.post(base + "/result", headers=headers, json={**attempt, "status": "sent"}).status_code == 409


def test_mobile_composer_prepares_task_without_provider_or_send(client, db):
    from tests.test_communication import prepare
    from tests.test_sales import _ready

    lead, _, _ = _ready(client, db)
    _elig(client, lead, channel="instagram", contact_ref="https://instagram.com/test_shop")
    draft = prepare(client, lead, channel="instagram", execution_mode="mobile")["draft"]
    url = f"/api/communication/drafts/{draft['id']}"
    preview = client.post(url + "/preview").json()
    assert preview["issues"] == [], preview
    response = client.post(url + "/confirm", json={"preview_hash": preview["preview_hash"], "confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "mobile"
    db.expire_all()
    task = db.get(ManualTask, response.json()["task_id"])
    assert task.execution_mode == "mobile" and task.sent_at is None


def test_installed_facebook_uses_current_app_account_without_manual_name(client, db):
    tid, device, headers, heartbeat = social_task(client, db)
    heartbeat["accounts"] = {}
    heartbeat["account"] = ""
    heartbeat["installed"] = ["facebook"]
    assert client.post("/api/mobile/device/heartbeat", headers=headers, json=heartbeat).status_code == 200
    t = db.get(ManualTask, tid)
    from app.modules.sales.models import Channel, ChannelEligibility

    e = db.get(ChannelEligibility, t.eligibility_id)
    e.channel = Channel.facebook
    e.contact_ref = "https://facebook.com/test_shop"
    t.channel = Channel.facebook
    db.commit()
    p = client.post(
        f"/api/mobile/tasks/{tid}/preview", json={"device_id": device["device_id"], "preview_hash": "0" * 64}
    )
    assert p.status_code == 200, p.text
    assert p.json()["payload"]["sender_mode"] == "current_app"
    assert p.json()["payload"]["sender"] == "Facebook 当前登录账号"
