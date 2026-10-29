from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.modules.leads import workflows
from app.modules.leads.history import serialize
from tests.test_list_workflows import _new, setup  # noqa: F401


def test_history_does_not_invent_completion_time():
    task = SimpleNamespace(
        id=uuid4(),
        finished_at=None,
        history_scope=None,
        params={},
        results=[],
        status="completed",
        created_at=datetime(2026, 10, 29, tzinfo=UTC),
        step=1,
        steps=["overture"],
        error=None,
        started_by="tester",
    )
    record = serialize(task)
    assert record["finished_at"] is None
    assert record["phase"] == "legacy"
    assert record["scope_count"] is None
    task.params = {"phase": "sync"}
    task.results = [{"retry": 2}]
    assert serialize(task)["status"] == "partial"


def test_history_includes_both_modes_and_freezes_scope(setup, db):  # noqa: F811
    client = setup
    first = _new(client).json()["workflow"]
    task = db.get(workflows.Workflow, first["id"])
    task.status = "completed"
    workflows.save_progress(db, task)
    second = client.post("/api/batches/new/workflow", json={"kind": "enrich", "phase": "review"})
    assert second.status_code == 201, second.text
    result = client.get("/api/batches/new/enrichment-history")
    assert result.status_code == 200
    records = result.json()
    assert records[0]["phase"] == "review"
    assert records[0]["scope"] == "batch"
    assert records[0]["scope_count"] == 0
    assert records[0]["finished_at"] is None
    assert records[1]["phase"] == "sync"
    assert records[1]["finished_at"] is not None
    assert records[1]["status"] == "completed"


def test_single_store_history_uses_recorded_membership(setup, db):  # noqa: F811
    from app.modules.leads.models import Lead
    from tests.test_list_workflows import _advance

    client = setup
    task = _new(client).json()["workflow"]
    task = _advance(client, task)
    lead = client.get("/api/leads?batch_key=new").json()[0]
    records = client.get(f"/api/leads/{lead['id']}/enrichment-history").json()
    assert records[0]["id"] == task["id"]
    assert records[0]["scope_count"] == 3
    unrelated = Lead(source_key="unrelated", source_name="manual", name="Other")
    db.add(unrelated)
    db.commit()
    assert client.get(f"/api/leads/{unrelated.id}/enrichment-history").json() == []
