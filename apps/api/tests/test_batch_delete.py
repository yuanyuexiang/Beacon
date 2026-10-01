"""删除批次：处理过的也能删；只属于该批次的门店连同数据与文件一并删除；属于其他批次或有抑制记录的门店保留；
必须带确认；删除有审计。"""

from sqlalchemy import func, select

from app.core.files import resolve_within, store_bytes
from app.core.models import AuditLog
from app.modules.leads.models import Batch, BatchLead, Lead
from app.modules.menus.models import MenuAnalysis, MenuAsset
from app.modules.sales.models import ChannelEligibility, CostEntry, Event, ManualTask, Suppression
from tests.test_analysis import _upload
from tests.test_imports import CSV_A, CSV_B, create_batch, login, upload
from tests.test_sales import _elig, _ready


def _n(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_delete_requires_login_confirm_and_existing_batch(client, db):
    assert client.delete("/api/batches/b1", params={"confirm": "b1"}).status_code == 401
    assert client.get("/api/batches/b1/delete-preview").status_code == 401
    login(client, db)
    assert client.delete("/api/batches/nope", params={"confirm": "nope"}).status_code == 404
    assert client.get("/api/batches/nope/delete-preview").status_code == 404
    create_batch(client, "b1")
    assert client.delete("/api/batches/b1").status_code == 400
    assert client.delete("/api/batches/b1", params={"confirm": "B1"}).status_code == 400
    assert [b["batch_key"] for b in client.get("/api/batches").json()] == ["b1"]


def test_delete_empty_batch(client, db):
    login(client, db)
    create_batch(client, "b1")
    r = client.delete("/api/batches/b1", params={"confirm": "b1"})
    assert r.status_code == 200 and r.json()["leads_deleted"] == 0
    assert client.get("/api/batches").json() == []
    create_batch(client, "b1")  # 批次键可以重新使用


def test_delete_processed_batch_removes_leads_data_and_files(client, db):
    lead_id, a, c = _ready(client, db)  # 批次 b1：一家门店，含菜单文件、已审核分析、已审批文案
    e = _elig(client, lead_id).json()
    t = client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]}).json()
    client.post(f"/api/leads/{lead_id}/events", json={"event_key": "e1", "kind": "reply", "channel": "email"})
    batch_id = client.get("/api/batches").json()[0]["id"]
    cost = {"batch_id": batch_id, "category": "processing", "minutes": 5, "occurred_at": "2026-10-01T10:00:00Z"}
    assert client.post("/api/costs", json=cost).status_code == 201
    assert t["status"] == "pending"
    store_bytes(f"content/{lead_id}/sample.html", b"<html></html>")  # 样稿文件（文案类内容不落文件）
    evidence = resolve_within(f"evidence/{lead_id}")
    content = resolve_within(f"content/{lead_id}")
    assert evidence.is_dir() and content.is_dir()

    p = client.get("/api/batches/b1/delete-preview").json()
    assert p["leads_in_batch"] == 1 and p["leads_deleted"] == 1 and p["leads_kept_suppressed"] == 0
    assert p["menu_assets"] == 1 and p["analyses"] >= 2 and p["content_pieces"] == 1 and p["contacts"] == 1
    assert p["tasks"] == 1 and p["tasks_sent"] == 0 and p["events"] == 1 and p["cost_entries"] == 1
    assert _n(db, Lead) == 1  # 预览只读

    r = client.delete("/api/batches/b1", params={"confirm": "b1"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert {k: j[k] for k in p} == p and j["file_dirs_removed"] == 2
    for model in (Batch, BatchLead, Lead, MenuAsset, MenuAnalysis, ChannelEligibility, ManualTask, Event, CostEntry):
        assert _n(db, model) == 0, model.__name__
    assert not evidence.exists() and not content.exists()
    assert client.get(f"/api/leads/{lead_id}").status_code == 404
    log = db.scalar(select(AuditLog).where(AuditLog.action == "delete", AuditLog.entity == "batch"))
    assert log is not None and log.before["leads_deleted"] == 1 and log.before["batch_key"] == "b1"


def test_delete_keeps_leads_shared_with_other_batches(client, db):
    login(client, db)
    create_batch(client, "b1")
    create_batch(client, "b2")
    upload(client, "b1", CSV_A)  # fsa:416314 Fish Central、fsa:1408999 Vesper
    upload(client, "b2", CSV_B)  # fsa:416314 关联到 b2，另有 fsa:999001
    shared = next(x for x in client.get("/api/leads").json() if x["source_key"] == "fsa:416314")
    _upload(client, shared["id"], "two_col.pdf", "application/pdf")
    p = client.get("/api/batches/b1/delete-preview").json()
    assert (p["leads_in_batch"], p["leads_deleted"], p["leads_kept_other_batches"]) == (2, 1, 1)
    assert p["menu_assets"] == 0  # 保留门店的数据不计入删除
    assert client.delete("/api/batches/b1", params={"confirm": "b1"}).status_code == 200
    keys = sorted(x["source_key"] for x in client.get("/api/leads").json())
    assert keys == ["fsa:416314", "fsa:999001"]
    assert len(client.get(f"/api/leads/{shared['id']}/assets").json()) == 1
    assert resolve_within(f"evidence/{shared['id']}").is_dir()
    assert [b["batch_key"] for b in client.get("/api/batches").json()] == ["b2"]


def test_delete_keeps_suppressed_leads_so_suppression_survives(client, db):
    login(client, db)
    create_batch(client, "b1")
    upload(client, "b1", CSV_A)
    leads = {x["name"]: x["id"] for x in client.get("/api/leads").json()}
    r = client.post(f"/api/leads/{leads['Vesper']}/events", json={"event_key": "rej-1", "kind": "reject"})
    assert r.status_code == 200, r.text
    p = client.get("/api/batches/b1/delete-preview").json()
    assert (p["leads_deleted"], p["leads_kept_suppressed"]) == (1, 1)
    assert client.delete("/api/batches/b1", params={"confirm": "b1"}).status_code == 200
    # 被拒收的门店保留、抑制仍指向它；另一家已删除
    assert [x["name"] for x in client.get("/api/leads").json()] == ["Vesper"]
    sup = db.scalar(select(Suppression))
    assert sup is not None and str(sup.lead_id) == leads["Vesper"]
    # 重新导入同一名录：关联回原门店而不是新建，抑制继续生效
    create_batch(client, "b3")
    j = upload(client, "b3", CSV_A).json()
    assert (j["created_count"], j["linked_count"]) == (1, 1)
    assert len(client.get("/api/suppressions").json()) == 1
