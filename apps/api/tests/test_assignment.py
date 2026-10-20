"""销售总监、门店分配、请求数据隔离与交接，无真实网络或发送。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.models import Operator
from app.modules.leads.models import Lead
from app.modules.sales.models import ManualTask, TaskStatus
from tests.test_assets import setup_lead
from tests.test_auth import make_operator
from tests.test_imports import upload
from tests.test_menu_inquiry import inquiry
from tests.test_sales import _elig
from tests.test_users import session


def person(db, name, role):
    p = make_operator(db, name, "password-123")
    p.role = role
    db.commit()
    return p


@pytest.fixture
def team(client, db):
    identity = setup_lead(client, db)
    boss = person(db, "boss", "director")
    alice = person(db, "alice", "member")
    bob = person(db, "bob", "member")
    return identity, session(boss), session(alice), session(bob)


def assign(c, identity, target, old=None):
    return c.post(
        "/api/assignment/apply", json={"expected": {identity: old}, "assigned_to": target, "reason": "团队交接"}
    )


def ready(client, identity):
    piece = inquiry(client, identity).json()
    client.post(f"/api/content/{piece['id']}/approve", json={"decision": "approved"})
    elig = _elig(client, identity).json()
    response = client.post(
        f"/api/leads/{identity}/tasks", json={"eligibility_id": elig["id"], "content_id": piece["id"]}
    )
    assert response.status_code == 201, response.text
    return piece, elig, response.json()


def test_director_permissions_and_optimistic_transfer(client, db, team):
    identity, boss, alice, _ = team
    assert {p["username"] for p in boss.get("/api/assignment/members").json()} == {"alice", "bob"}
    assert boss.get("/api/users").status_code == 403
    assert boss.post("/api/gmail/disconnect").status_code == 403
    assert boss.put("/api/lead-policy", json={}).status_code == 403
    assert alice.get("/api/assignment/members").status_code == 403
    assert assign(alice, identity, "alice").status_code == 403
    assert assign(boss, identity, "alice").json()["items"][0]["changed"]
    preview = boss.post("/api/assignment/preview", json={"lead_ids": [identity]}).json()
    assert preview["expected"] == {identity: "alice"}
    assert "已变化" in assign(boss, identity, "bob").json()["items"][0]["error"]
    history = boss.get(f"/api/leads/{identity}/assignment-history").json()[0]
    assert history["after"]["assigned_to"] == "alice"
    assert history["operator"] == "boss"


def test_member_scope_details_files_analysis_export(client, db, team):
    from tests.test_analysis import _upload

    identity, boss, alice, bob = team
    aid = _upload(client, identity, "two_col.pdf", "application/pdf")
    analysis = client.post(f"/api/assets/{aid}/analyses").json()
    file = client.get(f"/api/analyses/{analysis['id']}/evidence").json()["file_url"]
    assign(boss, identity, "alice")
    assert [p["id"] for p in alice.get("/api/leads").json()] == [identity]
    assert bob.get("/api/leads").json() == []
    assert alice.get(f"/api/leads/{identity}").status_code == 200
    for path in [f"/api/leads/{identity}", f"/api/assets/{aid}", f"/api/analyses/{analysis['id']}", file]:
        assert bob.get(path).status_code == 404, path
    assert alice.get(file).status_code == 200
    assert bob.get("/api/batches").json() == []
    assert alice.get("/api/batches").json()[0]["candidate_count"] == 1
    assert "Test Restaurant" not in bob.get("/api/batches/b1/export.csv").text
    assert "Test Restaurant" in alice.get("/api/batches/b1/export.csv").text
    assert bob.patch(f"/api/leads/{identity}", json={"screening_class": "candidate"}).status_code == 404
    assert alice.get("/api/communication/assignees").json() == [{"username": "alice", "display_name": None}]


def test_inherit_owner_and_prevent_member_reassignment(client, db, team):
    from tests.test_communication import prepare

    identity, boss, alice, bob = team
    assign(boss, identity, "alice")
    draft = prepare(client, identity)["draft"]
    assert draft["assigned_to"] == "alice"
    for value in ["bob", None]:
        assert alice.patch(f"/api/communication/drafts/{draft['id']}", json={"assigned_to": value}).status_code == 403
    assert bob.patch(f"/api/communication/drafts/{draft['id']}", json={"notes": "stolen"}).status_code == 404
    assert (
        alice.post("/api/communication/prepare", json={"lead_ids": [identity], "assigned_to": "bob"}).status_code == 403
    )


def test_handover_pauses_tasks_and_preserves_sent_history(client, db, team):
    from app.modules.gmail.models import EmailDelivery
    from app.modules.sales.preparation import Preparation

    identity, boss, alice, bob = team
    assign(boss, identity, "alice")
    piece, elig, task = ready(client, identity)
    assert task["assigned_to"] == "alice"
    sent = ManualTask(
        lead_id=uuid.UUID(identity),
        channel="email",
        eligibility_id=uuid.UUID(elig["id"]),
        content_id=uuid.UUID(piece["id"]),
        content_hash=piece["content_hash"],
        status=TaskStatus.sent_manual,
        created_by="alice",
        assigned_to="alice",
        sent_by="alice",
        sent_at=datetime.now(UTC),
    )
    db.add(sent)
    draft = Preparation(
        lead_id=uuid.UUID(identity),
        channel="phone",
        execution_mode="manual",
        assigned_to="alice",
        status="draft",
        created_by="tester",
    )
    db.add(draft)
    d = EmailDelivery(
        task_id=uuid.UUID(task["id"]),
        status="queued",
        payload={},
        approval_token="old",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        request_key="test",
    )
    db.add(d)
    db.commit()
    sent_id, delivery_id, draft_id = sent.id, d.id, draft.id
    assert assign(boss, identity, "bob", "alice").json()["items"][0]["changed"]
    assert alice.get(f"/api/leads/{identity}").status_code == 404
    assert bob.get(f"/api/leads/{identity}").status_code == 200
    metrics = {p["username"]: p for p in boss.get("/api/assignment/members").json()}
    assert metrics["bob"]["last_communication_at"] is not None
    assert metrics["bob"]["leads"] == 1 and metrics["alice"]["leads"] == 0
    db.info.pop("member_scope", None)
    db.expire_all()
    t = db.get(ManualTask, uuid.UUID(task["id"]))
    assert t.assigned_to == "bob" and t.status == TaskStatus.paused
    assert db.get(ManualTask, sent_id).sent_by == "alice"
    assert db.get(EmailDelivery, delivery_id).status == "cancelled"
    assert db.get(EmailDelivery, delivery_id).approval_token is None
    assert db.get(Preparation, draft_id).assigned_to == "bob"


def test_unknown_send_requires_reconciliation(client, db, team):
    from app.modules.gmail.models import EmailDelivery

    identity, boss, alice, bob = team
    assert alice.get("/api/leads").json() == []
    assign(boss, identity, "alice")
    _, _, t = ready(client, identity)
    db.add(
        EmailDelivery(
            task_id=uuid.UUID(t["id"]),
            status="unknown",
            payload={},
            expires_at=datetime.now(UTC),
            request_key="unknown",
        )
    )
    db.commit()
    assert "对账" in assign(boss, identity, "bob", "alice").json()["items"][0]["error"]
    assert alice.get(f"/api/leads/{identity}").status_code == 200
    assert bob.get(f"/api/leads/{identity}").status_code == 404


def test_cross_batch_one_owner_inactive_target_and_reclaim(client, db, team):
    identity, boss, alice, _ = team
    client.post("/api/batches", json={"batch_key": "second", "country": "GB", "source_name": "manual"})
    lead = db.get(Lead, uuid.UUID(identity))
    upload(client, "second", f"source_key,name\n{lead.source_key},Same Store\n")
    assign(boss, identity, "alice")
    assert alice.get("/api/leads?batch_key=second").json()[0]["assigned_to"] == "alice"
    assert alice.get("/api/leads?batch_key=b1").json()[0]["assigned_to"] == "alice"
    client.get("/api/auth/me")
    p = db.scalar(select(Operator).where(Operator.username == "bob"))
    p.is_active = False
    db.commit()
    assert assign(boss, identity, "bob", "alice").status_code == 422
    assert assign(boss, identity, None, "alice").json()["items"][0]["changed"]
    assert alice.get("/api/leads").json() == []


def test_foreign_content_tasks_deliveries_and_insert_are_denied(client, db, team):
    from app.modules.gmail.models import EmailDelivery

    identity, boss, alice, bob = team
    assign(boss, identity, "bob")
    piece, _, task = ready(client, identity)
    db.add(
        EmailDelivery(
            task_id=uuid.UUID(task["id"]),
            status="preview",
            payload={},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            request_key="private",
        )
    )
    db.commit()
    assert alice.get(f"/api/content/{piece['id']}").status_code == 404
    assert alice.post(f"/api/content/{piece['id']}/approve", json={"decision": "approved"}).status_code == 404
    assert alice.post(f"/api/tasks/{task['id']}/open").status_code == 404
    assert alice.get("/api/tasks").json() == []
    assert alice.get("/api/gmail/deliveries").json() == []
    assert bob.get("/api/gmail/deliveries").json()[0]["status"] == "preview"
    r = alice.post(
        f"/api/leads/{identity}/eligibility",
        json={"channel": "phone", "contact_ref": "+441234123456", "eligibility": "unknown"},
    )
    assert r.status_code in {403, 404}


def test_viewer_and_director_account_management(client, db, team):
    identity, _, _, _ = team
    viewer = session(person(db, "reader", "viewer"))
    assert assign(viewer, identity, "alice").status_code == 403
    assert viewer.get("/api/leads").status_code == 200
    response = client.post(
        "/api/users", json={"username": "newboss", "role": "director", "initial_password": "Start1234"}
    )
    assert response.status_code == 201 and response.json()["role"] == "director"


def test_worker_rechecks_current_owner_and_disabled_assignee(client, db, team):
    from app.modules.sales import service

    identity, boss, _, _ = team
    assign(boss, identity, "alice")
    _, _, t = ready(client, identity)
    task = db.get(ManualTask, uuid.UUID(t["id"]))
    lead = db.get(Lead, uuid.UUID(identity))
    lead.assigned_to = "bob"
    db.commit()
    with pytest.raises(service.SalesError, match="无门店权限"):
        service.check_task_owner(db, task)
    lead.assigned_to = "alice"
    p = db.scalar(select(Operator).where(Operator.username == "alice"))
    p.is_active = False
    db.commit()
    with pytest.raises(service.SalesError, match="停用"):
        service.check_task_owner(db, task)
