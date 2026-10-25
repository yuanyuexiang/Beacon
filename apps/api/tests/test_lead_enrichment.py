import uuid

from sqlalchemy import select, update

from app.modules.leads import enrichment, workflows
from app.modules.leads.models import Lead
from app.modules.leads.worker import tick
from tests.test_imports import CSV_A, create_batch, login, upload


def setup(client, db):
    login(client, db)
    create_batch(client)
    upload(client, "b1", CSV_A)
    lead = client.get("/api/leads?batch_key=b1").json()[0]
    return lead["id"], f"/api/leads/{lead['id']}/enrichment"


def test_read_only_and_reuse_batch_cross_membership(client, db, monkeypatch):
    identity, url = setup(client, db)
    monkeypatch.setattr(
        enrichment, "execute_item", lambda *a: (_ for _ in ()).throw(AssertionError("GET called external work"))
    )
    data = client.get(url).json()
    assert data["task"] is None
    assert next(x for x in data["items"] if x["key"] == "website")["needed"]
    task = client.post("/api/batches/b1/workflow", json={}).json()
    assert client.get(url).json()["task"]["id"] == task["id"]
    result = client.post(url, json={}).json()
    assert result["reused"] is True
    assert result["task"]["single"] is False
    assert result["task"]["results"] == []
    assert client.post(url + f"/{task['id']}/cancel").status_code == 404
    assert len(db.scalars(select(workflows.Workflow)).all()) == 1


def test_single_queue_only_selected_and_failures_do_not_block(client, db, monkeypatch):
    identity, url = setup(client, db)
    calls = []

    def execute(db, batch, task, lead, op, key):
        calls.append((str(lead.id), key, task.params["mode"]))
        if key == "website":
            raise ValueError("官网未读取，已有资料保留")
        return "完成"

    monkeypatch.setattr(enrichment, "execute_item", execute)
    response = client.post(url, json={"mode": "refresh", "items": ["contacts", "website"]})
    assert response.status_code == 202, response.text
    task = response.json()["task"]
    assert client.post(url, json={}).json()["task"]["id"] == task["id"]
    assert client.post("/api/batches/b1/workflow", json={}).status_code == 409
    assert tick(db)
    assert tick(db)
    assert not tick(db)
    data = client.get(url).json()["task"]
    assert data["status"] == "failed"
    assert [x["status"] for x in data["results"]] == ["failed", "completed"]
    assert calls == [(identity, "website", "refresh"), (identity, "contacts", "refresh")]
    # Single tasks must not become an incompatible list workflow.
    assert client.get("/api/batches/b1/workflow").json() is None
    assert client.post(f"/api/batches/b1/workflow/{task['id']}/advance").status_code == 404


def test_cancel_is_not_overwritten_by_late_results(client, db, monkeypatch):
    _, url = setup(client, db)
    task = client.post(url, json={"items": ["contacts"]}).json()["task"]

    def execute(session, batch, row, *args):
        session.execute(update(workflows.Workflow).where(workflows.Workflow.id == row.id).values(status="cancelled"))
        session.commit()
        return "late result"

    monkeypatch.setattr(enrichment, "execute_item", execute)
    assert tick(db)
    assert client.get(url).json()["task"]["status"] == "cancelled"
    assert not tick(db)
    assert client.post(url + f"/{task['id']}/cancel").status_code == 200


def test_continue_skips_fresh_but_refresh_is_explicit(client, db, monkeypatch):
    _, url = setup(client, db)
    monkeypatch.setattr(enrichment, "items", lambda *args: [dict(key="contacts", needed=False)])
    assert client.post(url, json={"items": ["contacts"]}).json()["task"] is None
    task = client.post(url, json={"mode": "refresh", "items": ["contacts"]}).json()["task"]
    assert task["steps"] == ["contacts"]
    row = db.get(workflows.Workflow, uuid.UUID(task["id"]))
    row.status = "running"  # Recover a process that exited after claiming work.
    db.commit()
    monkeypatch.setattr(enrichment, "execute_item", lambda *args: "done")
    assert tick(db)
    assert client.get(url).json()["task"]["status"] == "completed"


def test_overlapping_batch_cannot_start_while_single_runs(client, db):
    identity, url = setup(client, db)
    create_batch(client, "b2")
    upload(client, "b2", CSV_A)
    old = client.post("/api/batches/b2/workflow", json={}).json()
    row = db.get(workflows.Workflow, uuid.UUID(old["id"]))
    row.status = "failed"
    db.commit()
    client.post(url, json={"items": ["contacts"]})
    assert client.post(f"/api/batches/b2/workflow/{old['id']}/resume").status_code == 409
    assert client.post("/api/batches/b2/workflow", json={}).status_code == 409
    lead = db.get(Lead, uuid.UUID(identity))
    assert lead is not None


def test_member_scope_and_permission_recheck(client, db, monkeypatch):
    from tests.test_assignment import person
    from tests.test_users import session

    identity, url = setup(client, db)
    seller = session(person(db, "seller2", "member"))
    lead = db.get(Lead, uuid.UUID(identity))
    assert lead is not None
    assert seller.get(url).status_code == 404
    lead.assigned_to = "seller2"
    db.commit()
    response = seller.post(url, json={"items": ["contacts"]})
    assert response.status_code == 202, response.text
    lead.assigned_to = None
    db.commit()
    monkeypatch.setattr(
        enrichment, "execute_item", lambda *args: (_ for _ in ()).throw(AssertionError("permission revoked"))
    )
    assert tick(db)
    row = db.get(workflows.Workflow, uuid.UUID(response.json()["task"]["id"]))
    assert row.status == "failed"


def test_single_overture_does_not_update_other_stores(client, db, monkeypatch):
    from app.integrations import overture
    from app.modules.leads import service
    from app.modules.leads.models import Batch

    identity, _ = setup(client, db)
    seen = []

    def match(name, *args):
        seen.append(name)
        return None

    monkeypatch.setattr(overture, "match", match)
    batch = db.scalar(select(Batch).where(Batch.batch_key == "b1"))
    service.enrich_overture(db, batch, places=[], lead_ids=[identity])
    lead = db.get(Lead, uuid.UUID(identity))
    assert seen == [lead.name]
    others = db.scalars(select(Lead).where(Lead.id != lead.id)).all()
    assert all(not (other.raw or {}).get("overture") for other in others)


def test_failed_item_remains_retryable_with_existing_data(client, db, monkeypatch):
    _, url = setup(client, db)
    monkeypatch.setattr(enrichment, "execute_item", lambda *args: (_ for _ in ()).throw(ValueError("连接暂时失败")))
    client.post(url, json={"items": ["contacts"]})
    assert tick(db)
    item = next(x for x in client.get(url).json()["items"] if x["key"] == "contacts")
    assert item["needed"] is True
    assert item["description"] == "连接暂时失败"
    assert item["updated_at"] is not None


def test_assigned_member_can_complete_single_task(client, db, monkeypatch):
    from tests.test_assignment import person
    from tests.test_users import session

    identity, url = setup(client, db)
    seller = session(person(db, "owner", "member"))
    lead = db.get(Lead, uuid.UUID(identity))
    lead.assigned_to = "owner"
    db.commit()
    assert seller.post(url, json={"items": ["contacts"]}).status_code == 202
    monkeypatch.setattr(enrichment, "execute_item", lambda *args: "已完成")
    assert tick(db)
    assert seller.get(url).json()["task"]["status"] == "completed"
