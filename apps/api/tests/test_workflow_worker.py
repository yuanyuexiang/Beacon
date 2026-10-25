import uuid

from app.modules.leads import workflows
from app.modules.leads.worker import tick
from tests.test_imports import create_batch, login


def test_explicit_queue_survives_page_and_process_and_cancel(client, db, monkeypatch):
    login(client, db)
    create_batch(client)
    task = client.post("/api/batches/b1/workflow", json={}).json()
    assert tick(db) is False  # Historical/not-yet-submitted work never starts itself.
    calls = []

    def advance(db, batch, row):
        calls.append(row.id)
        row.step += 1
        row.status = "completed"
        workflows.save_progress(db, row)
        return row

    monkeypatch.setattr(workflows, "advance", advance)
    url = f"/api/batches/b1/workflow/{task['id']}"
    assert client.post(url + "/resume").status_code == 200
    row = db.get(workflows.Workflow, uuid.UUID(task["id"]))
    row.status = "running"  # Interrupted old process; database lock was released.
    db.commit()
    assert tick(db) is True
    assert tick(db) is False
    assert len(calls) == 1
    task2 = client.post("/api/batches/b1/workflow", json={}).json()
    url2 = f"/api/batches/b1/workflow/{task2['id']}"
    client.post(url2 + "/resume")
    assert client.post(url2 + "/cancel").json()["status"] == "cancelled"
    assert tick(db) is False
    assert client.post(url2 + "/resume").json()["status"] == "cancelled"


def test_failed_worker_needs_explicit_retry(client, db, monkeypatch):
    login(client, db)
    create_batch(client)
    task = client.post("/api/batches/b1/workflow", json={}).json()
    url = f"/api/batches/b1/workflow/{task['id']}/resume"
    client.post(url)

    def fail(db, batch, row):
        row.status = "failed"
        row.error = "network"
        workflows.save_progress(db, row)
        return row

    monkeypatch.setattr(workflows, "advance", fail)
    assert tick(db)
    assert not tick(db)
    resumed = client.post(url).json()
    assert resumed["params"]["retry_requested"] is True
    assert tick(db)
