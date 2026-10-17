"""准备可恢复、不绕过审批、重复操作复用、实际执行与回复闭环。"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.models import Operator
from app.modules.sales.workbench import manual_target
from tests.test_assets import setup_lead
from tests.test_imports import upload
from tests.test_sales import _elig, _ready


def prepare(client, identity, **kw):
    response = client.post("/api/communication/prepare", json={"lead_ids": [identity], **kw})
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


def activate(client, draft):
    return client.post("/api/communication/activate", json={"draft_ids": [draft]}).json()["items"][0]


def test_incomplete_draft_survives_and_reuses_without_task(client, db):
    identity = setup_lead(client, db)
    draft = prepare(client, identity, batch_key="b1")["draft"]
    assert len(draft["blockers"]) == 2
    assert prepare(client, identity)["draft"]["id"] == draft["id"]
    assert "error" in activate(client, draft["id"])
    assert client.get(f"/api/tasks?lead_id={identity}").json() == []
    assert client.get(f"/api/communication/leads/{identity}").json()["progress"]["status"] == "preparing"
    assert client.get("/api/leads").json()[0]["communication_progress"]["status"] == "preparing"


def test_activate_open_sent_reply_and_suppression(client, db):
    identity, _, _ = _ready(client, db)
    _elig(client, identity)
    draft = prepare(client, identity, batch_key="b1")["draft"]
    assert not draft["blockers"]
    task = activate(client, draft["id"])
    assert not task["reused"]
    assert activate(client, draft["id"])["task_id"] == task["task_id"]
    assert prepare(client, identity)["existing_task"]["id"] == task["task_id"]
    opened = client.post(f"/api/communication/tasks/{task['task_id']}/manual-open")
    assert opened.status_code == 200, opened.text
    assert opened.json()["url"].startswith("mailto:")
    assert client.get(f"/api/tasks?lead_id={identity}").json()[0]["sent_at"] is None
    sent = client.post(f"/api/tasks/{task['task_id']}/sent", json={"sent_at": datetime.now(UTC).isoformat()})
    assert sent.status_code == 200
    assert prepare(client, identity)["existing_task"]["id"] == task["task_id"]
    followup = prepare(client, identity, purpose="followup")["draft"]
    assert followup and followup["id"] != draft["id"]
    next_task = activate(client, followup["id"])
    event = {"event_key": "manual:reply", "kind": "reply", "channel": "email"}
    assert client.post(f"/api/leads/{identity}/events", json=event).status_code == 200
    context = client.get(f"/api/communication/leads/{identity}").json()
    assert context["progress"]["status"] == "replied"
    assert next(t for t in context["tasks"] if t["id"] == next_task["task_id"])["status"] == "paused"
    assert client.post(f"/api/communication/tasks/{next_task['task_id']}/manual-open").status_code == 409
    assert client.get(f"/api/communication/activity/{identity}").json()["timeline"]
    client.post(f"/api/leads/{identity}/events", json={**event, "event_key": "manual:stop", "kind": "unsubscribe"})
    assert "error" in prepare(client, identity)
    assert client.get(f"/api/communication/leads/{identity}").json()["progress"]["status"] == "suppressed"


def test_cross_customer_and_channel_guards_and_partial_batch(client, db):
    identity, _, piece = _ready(client, db)
    eligibility = _elig(client, identity).json()
    upload(client, "b1", "fhrsid,name\n2,Second Restaurant\n")
    other = next(x["id"] for x in client.get("/api/leads").json() if x["id"] != identity)
    draft = prepare(client, other)["draft"]
    for field, value in [("eligibility_id", eligibility["id"]), ("content_id", piece["id"])]:
        assert client.patch(f"/api/communication/drafts/{draft['id']}", json={field: value}).status_code == 422
    assert (
        client.patch(
            f"/api/communication/drafts/{draft['id']}", json={"follow_up_at": "2026-10-20T12:00:00"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/communication/prepare", json={"lead_ids": [other], "channel": "tiktok", "execution_mode": "gmail"}
        ).status_code
        == 422
    )
    result = client.post("/api/communication/prepare", json={"lead_ids": [identity, str(uuid.uuid4()), other]}).json()[
        "items"
    ]
    assert len(result) == 3 and "error" in result[1] and result[2]["draft"]["id"] == draft["id"]
    event = {"event_key": "global-key", "kind": "reply", "channel": "email"}
    client.post(f"/api/leads/{identity}/events", json=event)
    assert client.post(f"/api/leads/{other}/events", json=event).status_code == 409


def test_activation_rechecks_content_version_and_approval(client, db):
    identity, _, piece = _ready(client, db)
    _elig(client, identity)
    draft = prepare(client, identity)["draft"]
    client.post(f"/api/content/{piece['id']}/revise", json={"body_text": piece["body_text"] + " Updated."})
    assert "审批" in activate(client, draft["id"])["error"]
    assert client.get(f"/api/tasks?lead_id={identity}").json() == []
    client.post(f"/api/content/{piece['id']}/approve", json={"decision": "approved"})
    # 外部提交旧版本审批仍不足以绕过内容版本校验。
    assert "error" in activate(client, draft["id"])


def test_group_filter_owner_and_viewer_permissions(client, db):
    from tests.test_users import create, session

    identity, _, _ = _ready(client, db)
    _elig(client, identity)
    assigned = create(client, "owner", "member")
    draft = prepare(client, identity, assigned_to="owner", batch_key="b1")["draft"]
    group = str(uuid.uuid4())
    result = client.post(
        "/api/communication/activate", json={"draft_ids": [str(uuid.uuid4()), draft["id"]], "group_id": group}
    ).json()["items"]
    assert "error" in result[0] and result[1]["task_id"]
    overview = client.get(f"/api/communication/overview?preparation_group={group}&assigned_to=owner").json()
    assert overview["total"] == 1
    assert client.get(f"/api/communication/overview?preparation_group={uuid.uuid4()}").json()["total"] == 0
    task = client.get(f"/api/communication/leads/{identity}").json()["tasks"][0]
    assert task["assigned_to"] == assigned["username"]
    viewer = create(client, "reader", "viewer")
    viewer_op = db.scalar(select(Operator).where(Operator.username == viewer["username"]))
    viewer_op.must_change_password = False
    db.commit()
    reader = session(viewer_op)
    assert reader.get("/api/communication/overview").status_code == 200
    for path, payload in [
        ("/api/communication/prepare", {"lead_ids": [identity]}),
        ("/api/communication/activate", {"draft_ids": [draft["id"]]}),
    ]:
        assert reader.post(path, json=payload).status_code == 403


@pytest.mark.parametrize(
    "channel,target",
    [
        ("linkedin", "https://facebook.com/test"),
        ("facebook", "javascript:alert(1)"),
        ("tiktok", "https://127.0.0.1/x"),
        ("instagram", "https://instagram.com.evil.test/a"),
        ("email", "a@example.com?bcc=evil@example.com"),
    ],
)
def test_unsafe_manual_targets(channel, target):
    assert manual_target(channel, target) is None


@pytest.mark.parametrize(
    "channel,target",
    [
        ("linkedin", "https://www.linkedin.com/company/test"),
        ("facebook", "https://facebook.com/test"),
        ("tiktok", "https://www.tiktok.com/@test"),
        ("instagram", "https://instagram.com/test"),
    ],
)
def test_platform_targets(channel, target):
    assert manual_target(channel, target) == target
