"""D10：一条失败不终止整批；续跑只重做失败/超时的 job；成功的不重复分析；重复启动不重复 job；不支持步骤明确报错。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.modules.leads import runs
from tests.test_imports import create_batch, login, upload

FIX = Path(__file__).parent / "fixtures"
CSV = "fhrsid,name\n1,A\n2,B\n3,C\n"


def _setup(client, db):
    login(client, db)
    create_batch(client, "b1")
    upload(client, "b1", CSV)
    leads = {x["name"]: x["id"] for x in client.get("/api/leads").json()}
    good = (FIX / "two_col.pdf").read_bytes()
    bad = b"%PDF-1.4 this is not a real pdf"  # 魔数正确但内容损坏 → 解析失败
    client.post(f"/api/leads/{leads['A']}/assets/upload", files={"file": ("a.pdf", good, "application/pdf")})
    client.post(f"/api/leads/{leads['B']}/assets/upload", files={"file": ("b.pdf", bad, "application/pdf")})
    client.post(f"/api/leads/{leads['C']}/assets", json={"url": "http://127.0.0.1/menu.pdf"})  # 抓取失败（内网阻断）
    return leads


def test_fetch_then_analyze_in_same_run(client, db, monkeypatch):
    """同一轮内抓取成功的文件也应被分析（抓取后重新规划）。"""
    import httpx

    from app.integrations import fetcher
    from app.modules.menus import service as menu_service

    leads = _setup(client, db)
    monkeypatch.setattr(fetcher, "_is_public_host", lambda h, resolve=True: True)
    tr = httpx.MockTransport(
        lambda req: httpx.Response(
            200, content=(FIX / "two_col.pdf").read_bytes(), headers={"content-type": "application/pdf"}
        )
    )
    orig = menu_service.fetch_asset
    monkeypatch.setattr(menu_service, "fetch_asset", lambda db_, asset, transport=None: orig(db_, asset, transport=tr))
    r = client.post("/api/batches/b1/runs", json={"steps": ["fetch", "analyze"]}).json()
    c_jobs = [j for j in r["jobs"] if j["lead_id"] == leads["C"]]
    assert {j["step"] for j in c_jobs} == {"fetch", "analyze"} and all(j["status"] == "succeeded" for j in c_jobs)


def test_run_isolates_failures_and_resumes(client, db):
    leads = _setup(client, db)
    r = client.post("/api/batches/b1/runs", json={"steps": ["fetch", "analyze"]})
    assert r.status_code == 201, r.text
    run = r.json()
    by = {(j["lead_id"], j["step"]): j for j in run["jobs"]}
    assert by[(leads["A"], "analyze")]["status"] == "succeeded"
    assert by[(leads["B"], "analyze")]["status"] == "failed" and by[(leads["B"], "analyze")]["error"]
    assert by[(leads["C"], "fetch")]["status"] == "failed" and "公网" in by[(leads["C"], "fetch")]["error"]
    assert run["status"] == "completed_with_failures" and run["totals"] == {
        "pending": 0,
        "running": 0,
        "succeeded": 1,
        "failed": 2,
    }
    # 分析 B 的失败也被记录为 failed 分析版本，不伪装成功
    aid_b = client.get(f"/api/leads/{leads['B']}/assets").json()[0]["id"]
    assert client.get(f"/api/assets/{aid_b}/analyses").json()[0]["status"] == "failed"
    # 续跑：只重做失败的两个；A 不重复分析
    r2 = client.post(f"/api/runs/{run['id']}/resume", json={"steps": ["fetch", "analyze"]}).json()
    by2 = {(j["lead_id"], j["step"]): j for j in r2["jobs"]}
    assert by2[(leads["A"], "analyze")]["attempts"] == 1 and by2[(leads["B"], "analyze")]["attempts"] == 2
    aid_a = client.get(f"/api/leads/{leads['A']}/assets").json()[0]["id"]
    assert len(client.get(f"/api/assets/{aid_a}/analyses").json()) == 1
    assert len(r2["jobs"]) == 3  # 没有重复规划


def test_stale_running_job_is_reset_on_resume(client, db):
    leads = _setup(client, db)
    run = client.post("/api/batches/b1/runs", json={"steps": ["analyze"], "max_jobs": 0}).json()
    assert run["status"] == "running" and all(j["status"] == "pending" for j in run["jobs"])
    job = db.scalar(select(runs.BatchJob).where(runs.BatchJob.lead_id == leads["A"]))
    job.status, job.started_at = runs.JobStatus.running, datetime.now(UTC) - timedelta(hours=2)  # 模拟进程中断
    db.commit()
    r = client.post(f"/api/runs/{run['id']}/resume", json={"steps": ["analyze"]}).json()
    j = next(x for x in r["jobs"] if x["lead_id"] == leads["A"])
    assert j["status"] == "succeeded" and j["attempts"] == 1
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "completed_with_failures"


def test_new_run_after_completion_has_no_duplicate_work(client, db):
    _setup(client, db)
    client.post("/api/batches/b1/runs", json={"steps": ["analyze"]})
    r = client.post("/api/batches/b1/runs", json={"steps": ["analyze"]}).json()
    assert [j["lead_id"] for j in r["jobs"]] and all(j["step"] == "analyze" for j in r["jobs"])
    assert r["totals"]["succeeded"] == 0 and r["totals"]["failed"] == 1  # 只剩失败的 B 需要重试；A 已有有效分析
    assert client.post("/api/batches/b1/runs", json={"steps": ["email"]}).status_code == 400
    assert len(client.get("/api/batches/b1/runs").json()) == 2  # 400 的请求不创建运行


def test_rules_version_bump_replans_analysis(client, db, monkeypatch):
    from app.modules.menus import analysis as rules

    _setup(client, db)
    client.post("/api/batches/b1/runs", json={"steps": ["analyze"]})
    monkeypatch.setattr(rules, "RULES_VERSION", "test-bump")
    r = client.post("/api/batches/b1/runs", json={"steps": ["analyze"]}).json()
    assert r["totals"]["succeeded"] >= 1  # A 被重新分析
