"""One preview binds a recipient and phone; no external messages are sent."""

import pytest

from app.modules.mobile.models import Execution
from app.modules.sales.models import ManualTask
from tests.test_communication import prepare
from tests.test_mobile import setup
from tests.test_sales import _elig


@pytest.mark.parametrize(
    "channel,contact,platform,action",
    [
        ("facebook", "https://facebook.com/test_shop", "facebook", "direct_message"),
        ("instagram", "https://instagram.com/test_shop", "instagram", "message_request"),
        ("linkedin", "https://linkedin.com/in/test-shop", "linkedin", "connection_request"),
        ("tiktok", "https://tiktok.com/@test_shop", "tiktok", "direct_message"),
        ("other_social", "https://youtube.com/@test_shop", "youtube", "contact_discovery"),
        ("other_social", "https://x.com/test_shop", "x", "direct_message"),
    ],
)
def test_one_confirmation_queues_correct_phone_and_recipient(client, db, channel, contact, platform, action):
    tid, device, headers, _ = setup(client, db)
    task = db.get(ManualTask, tid)
    eligibility = _elig(client, str(task.lead_id), channel=channel, contact_ref=contact).json()
    client.post(
        "/api/mobile/device/heartbeat",
        headers=headers,
        json={
            "protocol": 2,
            "account": "",
            "accounts": {},
            "installed": [platform],
            "ready": True,
            "accessibility": True,
            "app_version": "test",
        },
    )
    draft = prepare(
        client, str(task.lead_id), channel=channel, execution_mode="mobile", eligibility_id=eligibility["id"]
    )["draft"]
    url = f"/api/communication/drafts/{draft['id']}"
    choice = {"device_id": device["device_id"], "action": action}
    preview = client.post(url + "/preview", json=choice).json()
    assert preview["issues"] == [], preview
    assert db.query(Execution).count() == 0
    confirmed = client.post(
        url + "/confirm", json={**choice, "preview_hash": preview["preview_hash"], "confirmed": True}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "mobile_queued"
    job = db.query(Execution).one()
    assert job.snapshot["channel"] == platform and job.snapshot["action"] == action
    assert job.task_id == db.get(ManualTask, confirmed.json()["task_id"]).id
    assert (
        client.post(
            url + "/confirm", json={**choice, "preview_hash": preview["preview_hash"], "confirmed": True}
        ).json()["status"]
        == "existing"
    )
    assert db.query(Execution).count() == 1


def test_switch_recipient_keeps_independent_active_drafts(client, db):
    tid, device, _, _ = setup(client, db)
    task = db.get(ManualTask, tid)
    a = _elig(client, str(task.lead_id), channel="facebook", contact_ref="https://facebook.com/one").json()
    b = _elig(client, str(task.lead_id), channel="facebook", contact_ref="https://facebook.com/two").json()
    first = prepare(client, str(task.lead_id), channel="facebook", execution_mode="mobile", eligibility_id=a["id"])[
        "draft"
    ]
    second = prepare(client, str(task.lead_id), channel="facebook", execution_mode="mobile", eligibility_id=b["id"])[
        "draft"
    ]
    assert second["id"] != first["id"] and second["eligibility_id"] == b["id"]
    assert client.get(f"/api/communication/drafts/{first['id']}").json()["eligibility_id"] == a["id"]


def test_phone_changed_after_preview_creates_no_task_or_job(client, db):
    from app.modules.mobile.models import Device

    tid, device, headers, _ = setup(client, db)
    original = db.get(ManualTask, tid)
    e = _elig(client, str(original.lead_id), channel="facebook", contact_ref="https://facebook.com/shop").json()
    client.post(
        "/api/mobile/device/heartbeat",
        headers=headers,
        json={
            "protocol": 2,
            "account": "",
            "accounts": {},
            "installed": ["facebook"],
            "ready": True,
            "accessibility": True,
            "app_version": "test",
        },
    )
    draft = prepare(client, str(original.lead_id), channel="facebook", execution_mode="mobile", eligibility_id=e["id"])[
        "draft"
    ]
    path = f"/api/communication/drafts/{draft['id']}"
    choice = {"device_id": device["device_id"], "action": "direct_message"}
    preview = client.post(path + "/preview", json=choice).json()
    assert not preview["issues"]
    db.get(Device, device["device_id"]).status = "paired"
    db.commit()
    result = client.post(path + "/confirm", json={**choice, "preview_hash": preview["preview_hash"], "confirmed": True})
    assert result.status_code == 409
    assert db.query(Execution).count() == 0 and db.query(ManualTask).count() == 1


def test_manual_mode_and_edited_message_survive_reselecting_contact(client, db):
    tid, _, _, _ = setup(client, db)
    lead = db.get(ManualTask, tid).lead_id
    contact = _elig(client, str(lead), channel="facebook", contact_ref="https://facebook.com/shop").json()
    draft = prepare(client, str(lead), channel="facebook", execution_mode="mobile", eligibility_id=contact["id"])[
        "draft"
    ]
    path = f"/api/communication/drafts/{draft['id']}"
    assert client.patch(path, json={"execution_mode": "manual"}).status_code == 200
    saved = client.put(
        path + "/message",
        json={
            "content_id": draft["content_id"],
            "body_text": draft["context"]["contents"][0]["body_text"] + "\nMy edited message",
            "subject": "",
        },
    )
    assert saved.status_code == 200, saved.text
    reopened = prepare(client, str(lead), channel="facebook", execution_mode="mobile", eligibility_id=contact["id"])[
        "draft"
    ]
    assert reopened["execution_mode"] == "manual" and reopened["content_id"] == saved.json()["content_id"]
