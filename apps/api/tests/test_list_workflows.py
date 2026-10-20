"""脱网验证名单检查点、固定参数、追加去重和跨请求互斥。"""

import uuid

import pytest
from sqlalchemy import select

from app.integrations import fsa
from app.modules.directory import service as directory
from app.modules.directory.models import Region, SyncRun
from app.modules.leads import runs, service, workflows
from app.modules.leads.models import Batch, BatchLead, Lead
from tests.test_fsa_sync import _transport
from tests.test_imports import create_batch, login


@pytest.fixture
def setup(client, db, monkeypatch):
    login(client, db)
    original = fsa.fetch_establishments
    region = Region(
        authority_id=277, name="Adur", business_type_ids=[1], type_versions={}, auto_sync=False, interval_hours=24
    )
    db.add(region)
    db.commit()
    run = SyncRun(authority_id=277, business_type_ids=[1], trigger="manual")
    db.add(run)
    db.commit()
    directory.apply_snapshot(db, run, {1: original(277, 1, transport=_transport(7, 0))})
    monkeypatch.setattr(fsa, "fetch_establishments", lambda *a, **k: original(277, 1, transport=_transport(7, 0)))
    monkeypatch.setattr(
        service, "enrich_overture", lambda *a, **k: {"leads": 3, "matched": 2, "website_set": 2, "phone_found": 1}
    )
    return client


def _new(client, key="new"):
    return client.post(
        "/api/lists",
        json={
            "batch_key": key,
            "country": "GB",
            "region": "Adur",
            "source_name": "fsa",
            "workflow": {"kind": "create", "authority_id": 277, "authority_name": "Adur", "sample_n": 3},
        },
    )


def _advance(client, task, key="new"):
    response = client.post(f"/api/batches/{key}/workflow/{task['id']}/advance")
    assert response.status_code == 200, response.text
    return response.json()


def test_create_and_resume_persist_params_skip_successful_fsa(setup, db, monkeypatch):
    client = setup
    response = _new(client)
    assert response.status_code == 201
    task = response.json()["workflow"]
    seed = task["params"]["seed"]
    assert seed is None
    assert task["params"]["selection"] == "ordered"
    task = _advance(client, task)
    assert task["step"] == 1 and task["results"][0]["selected"] == 3
    # 模拟失败，读取任务相当于刷新页面，再重试不得重跑 FSA。
    original = service.enrich_overture
    monkeypatch.setattr(service, "enrich_overture", lambda *a, **k: (_ for _ in ()).throw(ValueError("offline")))
    failed = _advance(client, task)
    assert failed["status"] == "failed" and failed["step"] == 1
    saved = client.get("/api/batches/new/workflow").json()
    assert saved["params"]["seed"] == seed and saved["results"] == task["results"]
    monkeypatch.setattr(service, "enrich_overture", original)
    monkeypatch.setattr(fsa, "fetch_establishments", lambda *a, **k: pytest.fail("成功步骤不应重跑"))
    resumed = _advance(client, saved)
    assert resumed["step"] == 2
    finished = _advance(client, _advance(client, _advance(client, resumed)))
    assert finished["status"] == "completed"
    assert _advance(client, finished) == finished
    assert len(client.get("/api/leads?batch_key=new").json()) == 3


def test_enrich_never_fetches_fsa_and_append_selects_new_members(setup, db, monkeypatch):
    client = setup
    task = _new(client).json()["workflow"]
    task = _advance(client, task)
    while task["status"] != "completed":
        task = _advance(client, task)
    append = client.post(
        "/api/batches/new/workflow",
        json={"kind": "append", "authority_id": 277, "authority_name": "Adur", "sample_n": 3},
    ).json()
    append = _advance(client, append)
    assert append["results"][0]["already_in_list"] == 3
    assert append["results"][0]["pool"] == 4 and append["results"][0]["selected"] == 3
    assert len(client.get("/api/leads?batch_key=new").json()) == 6
    while append["status"] != "completed":
        append = _advance(client, append)
    enrich = client.post("/api/batches/new/workflow", json={"kind": "enrich"}).json()
    assert enrich["steps"] == ["overture", "google", "screen", "contacts"]
    assert "google_request_limit" not in enrich["params"]["policy"]
    monkeypatch.setattr(fsa, "fetch_establishments", lambda *a, **k: pytest.fail("完善不应获取名录"))
    while enrich["status"] != "completed":
        enrich = _advance(client, enrich)


def test_pending_blocks_mutations_cancel_keeps_members(setup):
    client = setup
    task = _new(client).json()["workflow"]
    task = _advance(client, task)
    assert client.post("/api/batches/new/workflow", json={"kind": "enrich"}).status_code == 409
    for path, body in [
        ("screen", None),
        ("sync/fsa", {"authority_id": 277}),
        ("enrich/overture", {}),
        ("runs", {"steps": ["contacts"]}),
    ]:
        assert client.post(f"/api/batches/new/{path}", json=body).status_code == 409
    assert (
        client.post(
            "/api/imports", data={"batch_key": "new"}, files={"file": ("a.csv", b"name,source_key\nX,x\n")}
        ).status_code
        == 409
    )
    assert client.delete("/api/batches/new?confirm=new").status_code == 409
    cancelled = client.post(f"/api/batches/new/workflow/{task['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert len(client.get("/api/leads?batch_key=new").json()) == 3
    assert client.post("/api/batches/new/workflow", json={"kind": "enrich"}).status_code == 201


def test_lock_rejects_second_executor_but_allows_cancel(setup, db):
    client = setup
    task = _new(client).json()["workflow"]
    batch = db.scalar(select(Batch).where(Batch.batch_key == "new"))
    with workflows.lock(db, batch):
        assert client.post(f"/api/batches/new/workflow/{task['id']}/advance").status_code == 409
        assert client.post(f"/api/batches/new/workflow/{task['id']}/cancel").status_code == 200
    assert _advance(client, task)["status"] == "cancelled"


def test_atomic_pool_checkpoint_rolls_back_members_on_crash(setup, db, monkeypatch):
    client = setup
    task = _new(client).json()["workflow"]
    original = directory.add_to_batch

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("before checkpoint")

    monkeypatch.setattr(directory, "add_to_batch", crash)
    failed = _advance(client, task)
    assert failed["status"] == "failed" and failed["step"] == 0
    assert client.get("/api/leads?batch_key=new").json() == []
    monkeypatch.setattr(directory, "add_to_batch", original)
    retried = _advance(client, failed)
    assert retried["results"][0]["selected"] == 3
    assert retried["params"] == task["params"]


def test_contact_failure_reuses_run_and_successful_jobs(setup, db, monkeypatch):
    client = setup
    task = _new(client).json()["workflow"]
    for _ in range(4):
        task = _advance(client, task)
    # 给门店设置官网，三条 job 中一条首次失败。
    leads = db.scalars(select(Lead)).all()
    for lead in leads:
        lead.website = "https://example.test"
    db.commit()
    attempts: dict[uuid.UUID, int] = {}
    monkeypatch.setattr(runs, "_prefetch_websites", lambda *a: {})

    def collect(db, run, job, scans):
        attempts[job.lead_id] = attempts.get(job.lead_id, 0) + 1
        return {"pages_failed": int(job.lead_id == leads[0].id and attempts[job.lead_id] == 1)}

    monkeypatch.setattr(runs, "_collect_contacts", collect)
    failed = _advance(client, task)
    assert failed["status"] == "failed" and failed["results"][4]["totals"]["failed"] == 1
    run_id = failed["results"][4]["run_id"]
    finished = _advance(client, failed)
    assert finished["status"] == "completed" and finished["results"][4]["run_id"] == run_id
    assert sorted(attempts.values()) == [1, 1, 2]
    assert len(db.scalars(select(runs.BatchRun)).all()) == 1


def test_wrong_region_cross_batch_and_invalid_create_leave_no_batch(setup, db):
    client = setup
    response = client.post(
        "/api/lists",
        json={
            "batch_key": "invalid",
            "country": "GB",
            "region": "Adur",
            "source_name": "fsa",
            "workflow": {"kind": "create", "authority_id": 277, "authority_name": "Camden"},
        },
    )
    assert response.status_code == 422
    assert db.scalar(select(Batch).where(Batch.batch_key == "invalid")) is None
    task = _new(client).json()["workflow"]
    create_batch(client, "other")
    assert client.post(f"/api/batches/other/workflow/{task['id']}/advance").status_code == 404
    assert (
        client.post(
            "/api/batches/new/workflow", json={"kind": "append", "authority_id": 1, "authority_name": "Camden"}
        ).status_code
        == 409
    )  # 未完成任务先阻断
    client.post(f"/api/batches/new/workflow/{task['id']}/cancel")
    assert (
        client.post(
            "/api/batches/new/workflow", json={"kind": "append", "authority_id": 1, "authority_name": "Camden"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/batches/new/workflow", json={"kind": "append", "authority_id": 1, "authority_name": "Adur"}
        ).status_code
        == 422
    )


def test_crashed_contact_job_recovers_without_waiting_30_minutes(setup, db, monkeypatch):
    client = setup
    task = _new(client).json()["workflow"]
    for _ in range(4):
        task = _advance(client, task)
    workflow = db.get(workflows.Workflow, uuid.UUID(task["id"]))
    batch = db.get(Batch, workflow.batch_id)
    lead = db.scalar(select(Lead))
    lead.website = "https://example.test"
    db.commit()
    run = runs.start_run(db, batch, ["contacts"], "test")
    job = db.scalar(select(runs.BatchJob).where(runs.BatchJob.run_id == run.id))
    job.status = runs.JobStatus.running
    workflow.contact_run_id, workflow.status = run.id, "running"
    db.commit()
    monkeypatch.setattr(runs, "_prefetch_websites", lambda *a: {})
    monkeypatch.setattr(runs, "_collect_contacts", lambda *a: {"pages_failed": 0})
    finished = _advance(client, task)
    assert finished["status"] == "completed"
    db.refresh(job)
    assert job.status == runs.JobStatus.succeeded


def test_delete_completed_workflow_cascades(setup, db):
    client = setup
    task = _new(client).json()["workflow"]
    while task["status"] != "completed":
        task = _advance(client, task)
    assert client.delete("/api/batches/new?confirm=new").status_code == 200
    assert db.scalar(select(workflows.Workflow)) is None
    assert db.scalar(select(BatchLead)) is None


def test_append_all_links_existing_other_list_and_exhausts_pool(setup, db):
    client = setup
    create_batch(client, "other")
    other = db.scalar(select(Batch).where(Batch.batch_key == "other"))
    service.sync_fsa(db, other, 277, sample_n=None, transport=_transport(7, 0))
    task = _new(client).json()["workflow"]
    task = _advance(client, task)
    assert task["results"][0]["linked"] == 3 and task["results"][0]["created"] == 0
    while task["status"] != "completed":
        task = _advance(client, task)
    append = client.post(
        "/api/batches/new/workflow",
        json={"kind": "append", "authority_id": 277, "authority_name": "Adur", "sample_n": None},
    ).json()
    append = _advance(client, append)
    assert append["results"][0]["linked"] == 4 and append["results"][0]["selected"] == 4
    assert len(client.get("/api/leads?batch_key=new").json()) == 7
    assert len(db.scalars(select(Lead)).all()) == 7
    while append["status"] != "completed":
        append = _advance(client, append)
    last = client.post(
        "/api/batches/new/workflow",
        json={"kind": "append", "authority_id": 277, "authority_name": "Adur", "sample_n": 50},
    ).json()
    last = _advance(client, last)
    assert last["results"][0]["selected"] == 0 and last["results"][0]["pool"] == 0


def test_workflow_routes_require_authentication(client):
    assert client.get("/api/batches/any/workflow").status_code == 401
    assert client.post("/api/batches/any/workflow", json={"kind": "enrich"}).status_code == 401
    assert (
        client.post(
            "/api/lists",
            json={
                "batch_key": "new",
                "country": "GB",
                "region": "Adur",
                "source_name": "fsa",
                "workflow": {"kind": "create"},
            },
        ).status_code
        == 401
    )


def test_customer_default_fetches_entire_directory_without_random_sampling(setup, db, monkeypatch):
    import random

    client = setup
    monkeypatch.setattr(random.Random, "sample", lambda *a, **k: pytest.fail("客户名单不得随机抽样"))
    response = client.post(
        "/api/lists",
        json={
            "batch_key": "full",
            "country": "GB",
            "region": "Adur",
            "source_name": "fsa",
            "workflow": {"kind": "create", "authority_id": 277, "authority_name": "Adur"},
        },
    )
    assert response.status_code == 201
    task = response.json()["workflow"]
    assert task["params"]["sample_n"] is None and task["params"]["seed"] is None
    task = _advance(client, task, "full")
    assert task["results"][0]["selected"] == 7
    batch = db.scalar(select(Batch).where(Batch.batch_key == "full"))
    assert batch.sampling_seed is None and "全量" in batch.sampling_method
    assert len(client.get("/api/leads?batch_key=full").json()) == 7


def test_explicit_api_limit_uses_stable_order_without_randomness(setup, monkeypatch):
    import random

    client = setup
    monkeypatch.setattr(random.Random, "sample", lambda *a, **k: pytest.fail("不应抽样"))
    task = _new(client).json()["workflow"]
    task = _advance(client, task)
    assert task["results"][0]["selected"] == 3
    assert {row["source_key"] for row in client.get("/api/leads?batch_key=new").json()} == {
        "fsa:1000",
        "fsa:1001",
        "fsa:1002",
    }


def test_saved_legacy_task_replays_its_original_parameters(setup, db):
    import random

    client = setup
    task = _new(client).json()["workflow"]
    saved = db.get(workflows.Workflow, uuid.UUID(task["id"]))
    params = dict(saved.params)
    params.pop("selection")
    params.pop("source")
    saved.steps = ["fsa", "overture", "screen", "contacts"]
    params["seed"] = 123
    saved.params = params
    db.commit()
    resumed = _advance(client, task)
    assert resumed["results"][0]["selected"] == 3
    expected = set(random.Random(123).sample([f"fsa:{1000 + i}" for i in range(7)], 3))
    assert {row["source_key"] for row in client.get("/api/leads?batch_key=new").json()} == expected


def test_failed_workflow_allows_operations_and_new_task_archives_failure(setup, db, monkeypatch):
    client = setup
    task = _new(client).json()["workflow"]
    task = _advance(client, task)
    monkeypatch.setattr(service, "enrich_overture", lambda *a, **k: (_ for _ in ()).throw(ValueError("offline")))
    failed = _advance(client, task)
    assert failed["status"] == "failed"
    assert client.post("/api/batches/new/screen").status_code == 200
    assert (
        client.post(
            "/api/imports", data={"batch_key": "new"}, files={"file": ("a.csv", b"name,source_key\nX,manual:x\n")}
        ).status_code
        == 200
    )
    new_task = client.post("/api/batches/new/workflow", json={"kind": "enrich"})
    assert new_task.status_code == 201
    db.expire_all()
    previous = db.get(workflows.Workflow, uuid.UUID(failed["id"]))
    assert previous.status == "cancelled" and previous.error == "offline"
    assert _advance(client, failed)["status"] == "cancelled"
    assert len(client.get("/api/leads?batch_key=new").json()) == 4


@pytest.mark.parametrize("fail", [False, True])
def test_cancel_during_execution_cannot_be_overwritten(setup, db, monkeypatch, fail):
    client = setup
    task = _new(client).json()["workflow"]
    task = _advance(client, task)
    count = db.scalar(select(Batch.candidate_count).where(Batch.batch_key == "new"))

    def finish_after_cancel(*args, **kwargs):
        response = client.post(f"/api/batches/new/workflow/{task['id']}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        if fail:
            raise ValueError("late network failure")
        return {"matched": 1}

    monkeypatch.setattr(service, "enrich_overture", finish_after_cancel)
    result = _advance(client, task)
    assert result["status"] == "cancelled" and result["error"] is None
    assert _advance(client, result)["status"] == "cancelled"
    assert client.post(f"/api/batches/new/workflow/{task['id']}/cancel").json()["status"] == "cancelled"
    assert db.scalar(select(Batch.candidate_count).where(Batch.batch_key == "new")) == count


def test_contact_cancel_stops_next_job_and_keeps_finished_job(setup, db, monkeypatch):
    client = setup
    task = _new(client).json()["workflow"]
    for _ in range(4):
        task = _advance(client, task)
    for lead in db.scalars(select(Lead)).all():
        lead.website = "https://example.test"
    db.commit()
    monkeypatch.setattr(runs, "_prefetch_websites", lambda *a: {})
    handled = []

    def collect(session, run, job, scans):
        handled.append(job.id)
        response = client.post(f"/api/batches/new/workflow/{task['id']}/cancel")
        assert response.status_code == 200
        return {"pages_failed": 0, "pages_ok": 1}

    monkeypatch.setattr(runs, "_collect_contacts", collect)
    result = _advance(client, task)
    assert result["status"] == "cancelled"
    assert len(handled) == 1
    db.expire_all()
    jobs = db.scalars(select(runs.BatchJob)).all()
    assert sum(j.status == runs.JobStatus.succeeded for j in jobs) == 1
    assert sum(j.status == runs.JobStatus.pending for j in jobs) == 2
