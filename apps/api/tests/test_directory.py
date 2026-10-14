"""来源池与名单分离；全部外部请求使用本地夹具。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.integrations import fsa
from app.modules.directory import service
from app.modules.directory.models import Authority, Entry, Region, SyncRun, WorkerStatus
from app.modules.leads.models import BatchLead, Lead
from tests.test_fsa_sync import _est
from tests.test_imports import login


def rows(*ids):
    return [_est(i, "AwaitingInspection" if i == 0 else "5") for i in ids]


@pytest.fixture
def pool(client, db, monkeypatch):
    login(client, db)
    db.add(Authority(authority_id=277, name="Adur", region="South East", establishment_count=464))
    db.commit()
    data = {1: rows(0, 1, 2), 7843: [], 7844: []}

    def fetch(authority, type_id):
        return fsa.FsaPage("2026-10-15", len(data[type_id]), data[type_id])

    monkeypatch.setattr(fsa, "fetch_establishments", fetch)
    result = client.post("/api/directory/regions", json={"authority_id": 277, "business_type_ids": [1]})
    assert result.status_code == 201
    return client, data


def sync(client, db):
    assert client.post("/api/directory/regions/277/sync").status_code == 202
    assert service.tick(db)
    result = client.get("/api/directory/regions/277/syncs").json()[0]
    assert result["status"] == "completed", result
    return result


def create_list(client, key="pool-list", type_ids=None):
    response = client.post(
        "/api/lists",
        json={
            "batch_key": key,
            "country": "GB",
            "region": "Adur",
            "source_name": "fsa",
            "workflow": {
                "kind": "create",
                "authority_id": 277,
                "authority_name": "Adur",
                "business_type_ids": type_ids or [1],
            },
        },
    )
    return response


def advance(client, task, key="pool-list"):
    r = client.post(f"/api/batches/{key}/workflow/{task['id']}/advance")
    assert r.status_code == 200
    return r.json()


def test_first_sync_is_baseline_then_added_changed_missing_and_reappeared(pool, db):
    client, data = pool
    first = sync(client, db)
    assert first["counts"] == {
        "baseline": 3,
        "added": 0,
        "changed": 0,
        "missing": 0,
        "reappeared": 0,
        "unchanged": 0,
        "total": 3,
    }
    db.expire_all()
    original_seen = db.get(Entry, 1001).first_seen_at
    changed = _est(1)
    changed["BusinessName"] = "Changed Place"
    data[1] = [changed, _est(2), _est(3)]
    second = sync(client, db)
    assert second["counts"]["added"] == 1 and second["counts"]["changed"] == 1 and second["counts"]["missing"] == 1
    db.expire_all()
    assert not db.get(Entry, 1000).present
    assert db.get(Entry, 1001).first_seen_at == original_seen
    assert db.get(Entry, 1003).discovery_kind == "added"
    data[1] = [changed, _est(2), _est(3), _est(0)]
    third = sync(client, db)
    assert third["counts"]["reappeared"] == 1 and third["counts"]["missing"] == 0
    assert client.get("/api/directory/entries?authority_id=277&view=added").json()["total"] == 1
    assert client.get("/api/directory/entries?authority_id=277&view=missing").json()["total"] == 0
    changes = client.get(f"/api/directory/syncs/{second['id']}/changes").json()
    assert {c["kind"] for c in changes["items"]} == {"added", "changed", "missing"}
    assert any(c["diff"].get("name", {}).get("after") == "Changed Place" for c in changes["items"])


def test_pool_sync_does_not_change_batch_members_lead_fields_or_source_snapshot(pool, db, monkeypatch):
    client, data = pool
    sync(client, db)
    response = create_list(client)
    assert response.status_code == 201
    task = response.json()["workflow"]
    assert task["steps"][0] == "pool"
    monkeypatch.setattr(fsa, "fetch_establishments", lambda *a, **kw: pytest.fail("建立名单不应联网"))
    selected = advance(client, task)
    assert selected["results"][0]["selected"] == 3
    member = db.scalar(select(BatchLead))
    source = member.source_snapshot.copy()
    lead = db.get(Lead, member.lead_id)
    original_name = lead.name
    lead.website = "https://manual.example"
    lead.website_source = "manual"
    db.commit()
    # 直接构造成功同步，保证来源池变更不会修改业务层。
    data[1] = rows(0, 1, 2, 3)
    for raw in data[1]:
        raw["BusinessName"] = "New source name"
    run = service.enqueue(db, 277)
    service.apply_snapshot(db, run, {1: fsa.FsaPage("2026-10-16", 4, data[1])})
    db.expire_all()
    assert db.get(Lead, lead.id).name == original_name
    assert db.get(Lead, lead.id).website == "https://manual.example"
    assert db.get(BatchLead, member.id).source_snapshot == source
    assert len(client.get("/api/leads?batch_key=pool-list").json()) == 3
    assert client.get("/api/directory/entries?authority_id=277").json()["total"] == 4


def test_failed_multi_type_sync_and_incomplete_page_preserve_last_good_pool(pool, db, monkeypatch):
    client, data = pool
    sync(client, db)
    previous = client.get("/api/directory/regions").json()[0]["last_success_at"]
    client.patch("/api/directory/regions/277", json={"business_type_ids": [1, 7844], "auto_sync": False})

    def fetch(authority, type_id):
        if type_id == 7844:
            raise fsa.FsaConnectionError("offline")
        return fsa.FsaPage("2026-10-16", 1, rows(99))

    monkeypatch.setattr(fsa, "fetch_establishments", fetch)
    client.post("/api/directory/regions/277/sync")
    assert service.tick(db)
    assert client.get("/api/directory/regions").json()[0]["last_success_at"] == previous
    assert client.get("/api/directory/entries?authority_id=277").json()["total"] == 3
    assert client.get("/api/directory/regions/277/syncs").json()[0]["status"] == "failed"
    assert create_list(client, "unsupported", [7844]).status_code == 409
    assert all(b["batch_key"] != "unsupported" for b in client.get("/api/batches").json())
    monkeypatch.setattr(fsa, "fetch_establishments", lambda *a: fsa.FsaPage("2026-10-16", 4, rows(99)))
    client.post("/api/directory/regions/277/sync")
    service.tick(db)
    assert client.get("/api/directory/entries?authority_id=277").json()["total"] == 3


def test_queue_deduplicates_schedule_due_and_disabled_schedule(pool, db):
    client, data = pool
    a = client.post("/api/directory/regions/277/sync").json()
    b = client.post("/api/directory/regions/277/sync").json()
    assert a["id"] == b["id"]
    assert service.schedule_due(db, datetime.now(UTC) + timedelta(days=2)) == 0
    client.patch("/api/directory/regions/277", json={"business_type_ids": [1], "auto_sync": True, "interval_hours": 24})
    db.expire_all()
    region = db.get(Region, 277)
    assert region.next_sync_at is not None
    region.next_sync_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert service.schedule_due(db) == 1
    assert len(db.scalars(select(SyncRun)).all()) == 1
    assert service.schedule_due(db) == 0
    assert service.tick(db)
    region.next_sync_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert service.schedule_due(db) == 1
    assert len(db.scalars(select(SyncRun)).all()) == 2
    client.patch("/api/directory/regions/277", json={"business_type_ids": [1], "auto_sync": False})
    assert service.schedule_due(db, datetime.now(UTC) + timedelta(days=10)) == 0


def test_worker_restart_resumes_running_job_and_second_worker_does_not_execute(pool, db):
    client, data = pool
    run = db.scalar(select(SyncRun))
    run.status = "running"
    db.commit()
    engine = db.get_bind()
    with engine.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": service.WORKER_LOCK})
        try:
            assert service.tick(db) is False
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": service.WORKER_LOCK})
    assert service.tick(db)
    db.refresh(run)
    assert run.status == "completed" and len(db.scalars(select(SyncRun)).all()) == 1


def test_pool_selection_excludes_missing_and_pending_inspection_without_deleting_records(pool, db):
    client, data = pool
    sync(client, db)
    data[1] = rows(0, 2)
    sync(client, db)
    response = client.post(
        "/api/lists",
        json={
            "batch_key": "pool-list",
            "country": "GB",
            "region": "Adur",
            "source_name": "fsa",
            "workflow": {"kind": "create", "authority_id": 277, "authority_name": "Adur", "exclude_awaiting": True},
        },
    )
    assert response.status_code == 201
    task = advance(client, response.json()["workflow"])
    assert task["results"][0]["selected"] == 1
    assert client.get("/api/leads?batch_key=pool-list").json()[0]["source_key"] == "fsa:1002"
    assert client.get("/api/directory/entries?authority_id=277&view=all").json()["total"] == 3


def test_authority_cache_preserved_on_failure_and_all_endpoints_protected(client, db, monkeypatch):
    assert client.get("/api/directory/regions").status_code == 401
    assert client.get("/api/directory/status").status_code == 401
    assert client.post("/api/directory/regions", json={"authority_id": 277}).status_code == 401
    login(client, db)
    monkeypatch.setattr(fsa, "list_authorities", lambda: [{"id": 277, "name": "Adur", "region": "SE", "count": 464}])
    assert client.post("/api/directory/authorities/refresh").status_code == 200
    monkeypatch.setattr(fsa, "list_authorities", lambda: (_ for _ in ()).throw(ValueError("offline")))
    assert client.post("/api/directory/authorities/refresh").status_code == 502
    assert client.get("/api/directory/authorities").json()[0]["name"] == "Adur"
    assert client.post("/api/directory/regions", json={"authority_id": 999}).status_code == 422


def test_empty_complete_snapshot_marks_missing_and_worker_heartbeat(pool, db):
    client, data = pool
    sync(client, db)
    assert client.get("/api/directory/status").json()["online"] is False
    db.add(WorkerStatus(id="directory", heartbeat_at=datetime.now(UTC)))
    db.commit()
    assert client.get("/api/directory/status").json()["online"] is True
    data[1] = []
    result = sync(client, db)
    assert result["counts"]["missing"] == 3
    assert client.get("/api/directory/entries?authority_id=277&view=missing").json()["total"] == 3


def test_new_category_baseline_and_membership_link_keeps_existing_manual_data(pool, db, monkeypatch):
    client, data = pool
    sync(client, db)
    first = create_list(client)
    advance(client, first.json()["workflow"])
    lead = db.scalar(select(Lead).where(Lead.source_key == "fsa:1000"))
    lead.website = "https://manual.example"
    db.commit()
    second = create_list(client, "second")
    result = advance(client, second.json()["workflow"], "second")
    assert result["results"][0]["linked"] == 3 and result["results"][0]["created"] == 0
    assert db.get(Lead, lead.id).website == "https://manual.example"
    client.patch("/api/directory/regions/277", json={"business_type_ids": [1, 7843], "auto_sync": False})
    pub = _est(10)
    pub["BusinessTypeID"], pub["BusinessType"] = 7843, "Pub/bar/nightclub"
    data[7843] = [pub]
    new_category = sync(client, db)
    assert new_category["counts"]["baseline"] == 1 and new_category["counts"]["added"] == 0


def test_two_batches_select_same_pool_entries_concurrently_without_duplicate_leads(pool, db):
    from concurrent.futures import ThreadPoolExecutor

    client, _ = pool
    sync(client, db)
    first = create_list(client, "first").json()["workflow"]
    second = create_list(client, "second").json()["workflow"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(advance, client, first, "first"), executor.submit(advance, client, second, "second")]
        results = [future.result() for future in futures]
    assert all(result["step"] == 1 and result["status"] == "pending" for result in results)
    assert sum(result["results"][0]["created"] for result in results) == 3
    assert sum(result["results"][0]["linked"] for result in results) == 3
    assert len(db.scalars(select(Lead)).all()) == 3


def test_snapshot_database_failure_rolls_back_earlier_rows_and_preserves_good_version(pool, db):
    client, data = pool
    first = sync(client, db)
    db.expire_all()
    previous_name = db.get(Entry, 1000).name
    changed, invalid = _est(0), _est(99)
    changed["BusinessName"] = "Changed before error"
    invalid["BusinessName"] = "x" * 300
    data[1] = [changed, invalid]
    client.post("/api/directory/regions/277/sync")
    assert service.tick(db)
    db.expire_all()
    assert db.get(Entry, 1000).name == previous_name
    assert db.get(Entry, 1099) is None
    run = client.get("/api/directory/regions/277/syncs").json()[0]
    assert run["status"] == "failed" and "INSERT" not in run["error"]
    assert client.get("/api/directory/regions").json()[0]["type_versions"]["1"]["sync_id"] == first["id"]


def test_wrong_authority_response_does_not_mix_regions(pool, db):
    client, data = pool
    sync(client, db)
    other_region = _est(99)
    other_region["LocalAuthorityName"] = "Camden"
    data[1] = [other_region]
    client.post("/api/directory/regions/277/sync")
    assert service.tick(db)
    assert client.get("/api/directory/regions/277/syncs").json()[0]["status"] == "failed"
    assert client.get("/api/directory/entries?authority_id=277").json()["total"] == 3


def test_uk_pool_cannot_be_assigned_to_another_country(pool, db):
    client, data = pool
    sync(client, db)
    response = client.post(
        "/api/lists",
        json={
            "batch_key": "wrong-country",
            "country": "FR",
            "region": "Adur",
            "source_name": "fsa",
            "workflow": {"kind": "create", "authority_id": 277, "authority_name": "Adur"},
        },
    )
    assert response.status_code == 422
    assert all(row["batch_key"] != "wrong-country" for row in client.get("/api/batches").json())
