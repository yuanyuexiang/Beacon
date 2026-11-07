"""Phone tests use fake messages only; no device or external send."""

from datetime import timedelta

from sqlalchemy import select

from app.modules.mobile.models import Device, Execution
from app.modules.sales import service
from app.modules.sales.models import ManualTask
from tests.test_sales import _elig, _ready


def setup(client, db):
    lead, _, content = _ready(client, db)
    e = _elig(client, lead, channel="whatsapp", contact_ref="+447700900123").json()
    t = client.post(f"/api/leads/{lead}/tasks", json={"eligibility_id": e["id"], "content_id": content["id"]})
    assert t.status_code == 201, t.text
    code = client.post("/api/mobile/pairing").json()["code"]
    paired = client.post("/api/mobile/device/pair", json={"code": code, "label": "Test phone"})
    assert paired.status_code == 200, paired.text
    d = paired.json()
    headers = {"Authorization": "Bearer " + d["token"]}
    r = client.post(
        "/api/mobile/device/heartbeat",
        headers=headers,
        json={"account": "+447700900001", "ready": True, "accessibility": True, "app_version": "test"},
    )
    assert r.status_code == 200, r.text
    return t.json()["id"], d, headers, code


def enqueue(client, tid, device):
    path = f"/api/mobile/tasks/{tid}"
    args = {"device_id": device["device_id"], "preview_hash": "0" * 64}
    p = client.post(path + "/preview", json=args)
    assert p.status_code == 200, p.text
    args["preview_hash"] = p.json()["preview_hash"]
    j = client.post(path + "/confirm", json=args)
    assert j.status_code == 200, j.text
    return j.json(), args


def test_pairing_once_and_credentials_not_exposed(client, db):
    _, d, headers, code = setup(client, db)
    assert len(code) == 6 and code.isdigit()
    assert client.post("/api/mobile/device/pair", json={"code": code, "label": "Again"}).status_code == 409
    devices = client.get("/api/mobile/devices").text
    assert d["token"] not in devices and "token_hash" not in devices
    assert client.post("/api/mobile/device/claim", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post(f"/api/mobile/devices/{d['device_id']}/revoke").status_code == 200
    assert client.post("/api/mobile/device/claim", headers=headers).status_code == 401


def test_confirm_claim_start_result_and_duplicate(client, db):
    tid, d, headers, _ = setup(client, db)
    job, args = enqueue(client, tid, d)
    assert client.post(f"/api/mobile/tasks/{tid}/confirm", json=args).json()["id"] == job["id"]
    claimed = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    assert claimed["snapshot"]["target"] == "+447700900123"
    assert client.post("/api/mobile/device/claim", headers=headers).json()["job"] is None
    base = f"/api/mobile/device/jobs/{job['id']}"
    b = {"lease": claimed["lease"], "attempt": claimed["attempt"]}
    assert client.post(base + "/result", headers=headers, json={**b, "status": "sent"}).status_code == 409
    assert client.post(base + "/start", headers=headers, json=b).status_code == 200
    assert client.post(base + "/start", headers=headers, json=b).status_code == 409
    for _ in range(2):
        r = client.post(base + "/result", headers=headers, json={**b, "status": "sent"})
        assert r.status_code == 200, r.text
    db.expire_all()
    assert db.scalar(select(ManualTask)).status.value == "sent_manual"
    assert client.post(base + "/result", headers=headers, json={**b, "status": "failed"}).status_code == 409


def test_cancel_blocks_start_and_expired_lease_never_replays(client, db):
    tid, d, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, d)
    c = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    db.query(Execution).filter_by(id=job["id"]).update({"lease_until": service.now() - timedelta(seconds=1)})
    db.commit()
    assert client.post("/api/mobile/device/claim", headers=headers).json()["job"] is None
    assert client.get(f"/api/mobile/tasks/{tid}").json()["status"] == "unknown"
    assert (
        client.post(
            f"/api/mobile/device/jobs/{job['id']}/start",
            headers=headers,
            json={"lease": c["lease"], "attempt": c["attempt"]},
        ).status_code
        == 409
    )


def test_changed_sender_and_task_cancel_stop_execution(client, db):
    tid, d, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, d)
    c = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    assert client.post(f"/api/mobile/tasks/{tid}/cancel").json()["status"] == "cancelled"
    assert (
        client.post(
            f"/api/mobile/device/jobs/{job['id']}/start",
            headers=headers,
            json={"lease": c["lease"], "attempt": c["attempt"]},
        ).status_code
        == 409
    )


def test_device_owner_scope_and_preview_integrity(client, db):
    tid, d, _, _ = setup(client, db)
    device = db.scalar(select(Device))
    device.owner = "tester"
    db.commit()
    path = f"/api/mobile/tasks/{tid}/confirm"
    assert client.post(path, json={"device_id": d["device_id"], "preview_hash": "0" * 64}).status_code == 409
    assert not db.scalar(select(Execution))


def test_suppression_after_queue_blocks_claim(client, db):
    from app.modules.sales.models import Suppression, SuppressionScope

    tid, d, headers, _ = setup(client, db)
    enqueue(client, tid, d)
    t = db.scalar(select(ManualTask))
    db.add(Suppression(lead_id=t.lead_id, scope=SuppressionScope.lead, reason="test", created_at=service.now()))
    db.commit()
    r = client.post("/api/mobile/device/claim", headers=headers)
    assert r.json()["job"] is None
    assert client.get(f"/api/mobile/tasks/{tid}").json()["status"] == "cancelled"


def test_revoked_device_can_settle_but_cannot_execute_again(client, db):
    tid, d, headers, _ = setup(client, db)
    j, _ = enqueue(client, tid, d)
    c = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    b = {"lease": c["lease"], "attempt": c["attempt"]}
    base = f"/api/mobile/device/jobs/{j['id']}"
    assert client.post(base + "/start", headers=headers, json=b).status_code == 200
    client.post(f"/api/mobile/devices/{d['device_id']}/revoke")
    assert client.post(base + "/result", headers=headers, json={**b, "status": "sent"}).json()["status"] == "sent"
    assert client.post(base + "/start", headers=headers, json=b).status_code == 401


def test_other_user_cannot_read_device_and_expired_pairing(client, db):
    from app.modules.mobile.models import Pairing
    from tests.test_assignment import person
    from tests.test_users import session

    _, _, _, _ = setup(client, db)
    other = session(person(db, "other", "member"))
    assert other.get("/api/mobile/devices").json() == []
    code = client.post("/api/mobile/pairing").json()["code"]
    for row in db.scalars(select(Pairing)):
        row.expires_at = service.now() - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/mobile/device/pair", json={"code": code, "label": "Expired"}).status_code == 409


def test_manual_path_blocked_while_mobile_queued(client, db):
    tid, d, _, _ = setup(client, db)
    enqueue(client, tid, d)
    assert client.post(f"/api/tasks/{tid}/open").status_code == 409
    assert client.post(f"/api/tasks/{tid}/cancel", json={"reason": "test"}).status_code == 409


def test_unknown_resolution_waits_for_lease_and_archives_late_result(client, db):
    tid, d, headers, _ = setup(client, db)
    j, _ = enqueue(client, tid, d)
    c = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    b = {"lease": c["lease"], "attempt": c["attempt"]}
    base = f"/api/mobile/device/jobs/{j['id']}"
    client.post(base + "/start", headers=headers, json=b)
    client.post(base + "/result", headers=headers, json={**b, "status": "unknown"})
    path = f"/api/mobile/tasks/{tid}/resolve"
    assert client.post(path, json={"sent": False, "reason": "Test reconciliation"}).status_code == 409
    row = db.scalar(select(Execution))
    row.lease_until = service.now() - timedelta(seconds=1)
    db.commit()
    assert client.post(path, json={"sent": False, "reason": "No sent message found"}).json()["status"] == "failed"
    late = client.post(base + "/result", headers=headers, json={**b, "status": "sent"})
    assert late.status_code == 200 and late.json()["status"] == "unknown"
    db.expire_all()
    result = db.scalar(select(Execution)).result
    assert result["resolution"]["sent"] is False and result["late_result"]["status"] == "sent"


def test_sender_change_cancels_prepared_job(client, db):
    tid, d, headers, _ = setup(client, db)
    enqueue(client, tid, d)
    client.post(
        "/api/mobile/device/heartbeat",
        headers=headers,
        json={"account": "+447700900002", "ready": True, "accessibility": True, "app_version": "test"},
    )
    assert client.get(f"/api/mobile/tasks/{tid}").json()["status"] == "cancelled"
    assert client.post("/api/mobile/device/claim", headers=headers).json()["job"] is None


def test_device_state_restores_account_and_counts_only_pending(client, db):
    tid, device, headers, _ = setup(client, db)
    state = client.post("/api/mobile/device/state", headers=headers).json()
    assert state["account"] == "+447700900001" and state["pending_count"] == 0
    enqueue(client, tid, device)
    assert client.post("/api/mobile/device/state", headers=headers).json()["pending_count"] == 1
    client.post("/api/mobile/device/claim", headers=headers)
    assert client.post("/api/mobile/device/state", headers=headers).json()["pending_count"] == 0
    assert client.post("/api/mobile/device/state").status_code == 401


def test_pairing_refresh_expires_previous_code_and_returns_owner(client, db):
    setup(client, db)
    first = client.post("/api/mobile/pairing").json()
    second = client.post("/api/mobile/pairing").json()
    assert second["owner"] == "tester" and second["code"] != first["code"]
    assert client.post("/api/mobile/device/pair", json={"code": first["code"], "label": "old"}).status_code == 409
    paired = client.post("/api/mobile/device/pair", json={"code": second["code"], "label": "scan"})
    assert paired.status_code == 200 and paired.json()["owner"] == "tester"


def test_presence_without_execution_ready(client, db):
    _, d, headers, _ = setup(client, db)
    response = client.post(
        "/api/mobile/device/heartbeat", headers=headers, json={"ready": False, "app_version": "test", "protocol": 2}
    )
    assert response.status_code == 200
    phone = client.get("/api/mobile/devices").json()[0]
    assert phone["online"] is True and phone["status"] == "paired"


def test_remove_device_preserves_history_and_revokes_token(client, db):
    tid, d, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, d)
    assert client.delete(f"/api/mobile/devices/{d['device_id']}").status_code == 200
    assert client.get("/api/mobile/devices").json() == []
    assert (
        client.post(
            "/api/mobile/device/heartbeat", headers=headers, json={"ready": False, "app_version": "test", "protocol": 2}
        ).status_code
        == 401
    )
    db.expire_all()
    assert db.scalar(select(Device)).status == "revoked"
    assert db.scalar(select(Execution)).status == "cancelled"
    assert client.get(f"/api/mobile/tasks/{tid}").json()["id"] == job["id"]


def test_device_reports_name_without_changing_sender(client, db):
    _, d, headers, _ = setup(client, db)
    response = client.post(
        "/api/mobile/device/heartbeat",
        headers=headers,
        json={"label": "Xiaomi 测试手机", "account": "+447700900001", "app_version": "test"},
    )
    assert response.status_code == 200
    assert response.json()["label"] == "Xiaomi 测试手机"
    assert client.get("/api/mobile/devices").json()[0]["label"] == "Xiaomi 测试手机"


def test_device_disconnect_retains_pairing_and_unbind_revokes(client, db):
    _, device, headers, _ = setup(client, db)
    assert client.post("/api/mobile/device/disconnect", headers=headers).status_code == 200
    row = next(d for d in client.get("/api/mobile/devices").json() if str(d["id"]) == device["device_id"])
    assert row["online"] is False
    assert row["status"] == "paired"
    assert client.post("/api/mobile/device/state", headers=headers).status_code == 200
    assert (
        client.post(
            "/api/mobile/device/heartbeat",
            headers=headers,
            json={"account": "+447700900001", "ready": False, "accessibility": True, "app_version": "test"},
        ).status_code
        == 200
    )
    assert client.post("/api/mobile/device/unbind", headers=headers).status_code == 200
    assert client.post("/api/mobile/device/state", headers=headers).status_code == 401


def test_admin_phone_can_execute_task_assigned_to_another_authorized_member(client, db):
    from app.core.models import Operator
    from app.modules.leads.models import Lead

    tid, device, headers, _ = setup(client, db)
    task = db.get(ManualTask, tid)
    owner = db.scalar(select(Operator).where(Operator.username == "tester"))
    assert owner.role == "admin"
    member = Operator(username="phone-member", role="member", is_active=True, password_hash="unused")
    db.add(member)
    task.assigned_to = member.username
    db.get(Lead, task.lead_id).assigned_to = member.username
    db.commit()
    job, _ = enqueue(client, tid, device)
    claimed = client.post("/api/mobile/device/claim", headers=headers)
    assert claimed.json()["job"]["id"] == job["id"]
    assert db.get(ManualTask, tid).assigned_to == member.username


def test_member_phone_cannot_execute_another_members_task(client, db):
    import pytest
    from fastapi import HTTPException

    from app.core.models import Operator
    from app.modules.mobile.routes import check_device_access

    tid, _, _, _ = setup(client, db)
    device = db.scalar(select(Device))
    db.add(Operator(username="another-phone-owner", role="member", is_active=True, password_hash="unused"))
    device.owner = "another-phone-owner"
    db.commit()
    task = db.get(ManualTask, tid)
    with pytest.raises(HTTPException, match="任务负责人"):
        check_device_access(db, task.lead_id, device, task.assigned_to, "tester")


def test_mobile_readiness_reports_missing_accessibility_and_start_separately(client, db):
    tid, device, _, _ = setup(client, db)
    row = db.scalar(select(Device))
    row.status = "paired"
    row.capabilities = {**row.capabilities, "accessibility": False}
    db.commit()
    path = f"/api/mobile/tasks/{tid}/preview"
    response = client.post(path, json={"device_id": device["device_id"], "preview_hash": "0" * 64})
    assert response.status_code == 409
    assert "无障碍服务" in response.json()["detail"]
    row.capabilities = {**row.capabilities, "accessibility": True}
    db.commit()
    response = client.post(path, json={"device_id": device["device_id"], "preview_hash": "0" * 64})
    assert response.status_code == 409
    assert "任务页" in response.json()["detail"]
