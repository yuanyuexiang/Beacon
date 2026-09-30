"""FSA 同步：分页拉取、排除 AwaitingInspection、固定种子抽样、去重与跨批次关联；接口失败明确报错。不访问网络。"""

import httpx

from app.integrations import fsa
from app.modules.leads import service
from tests.test_imports import create_batch, login


def _est(i, rating="5"):
    return {
        "FHRSID": 1000 + i,
        "BusinessName": f"Place {i}",
        "AddressLine1": f"{i} Road",
        "PostCode": "N1 1AA",
        "BusinessTypeID": 1,
        "BusinessType": "Restaurant/Cafe/Canteen",
        "RatingValue": rating,
        "RatingDate": "2026-01-01",
        "geocode": {"latitude": "51.5", "longitude": "-0.1"},
    }


def _transport(n=7, awaiting=2):
    ests = [_est(i, "AwaitingInspection" if i < awaiting else "5") for i in range(n)]

    def handler(req):
        page = int(req.url.params.get("pageNumber", "1"))
        size = int(req.url.params.get("pageSize", "5000"))
        chunk = ests[(page - 1) * size : page * size]
        return httpx.Response(
            200,
            json={
                "meta": {
                    "extractDate": "2026-09-30T04:51:53",
                    "totalCount": n,
                    "totalPages": -(-n // size),
                    "pageSize": size,
                },
                "establishments": chunk,
            },
        )

    return httpx.MockTransport(handler)


def test_fetch_paginates_and_maps():
    page = fsa.fetch_establishments(106, 1, transport=_transport(n=7), page_size=3)
    assert page.total == 7 and len(page.establishments) == 7 and (page.extract_date or "").startswith("2026-09-30")
    row = fsa.to_lead_row(page.establishments[0])
    assert row["source_key"] == "fsa:1000" and row["lat"] == 51.5 and row["raw"]["RatingValue"] == "AwaitingInspection"


def test_sync_excludes_awaiting_samples_and_links(client, db):
    login(client, db)
    create_batch(client, "b1")
    from sqlalchemy import select

    from app.modules.leads.models import Batch

    b = db.scalar(select(Batch).where(Batch.batch_key == "b1"))
    r = service.sync_fsa(
        db,
        b,
        106,
        1,
        exclude_awaiting=True,
        sample_n=3,
        seed=7,
        operator="tester",
        transport=_transport(n=7, awaiting=2),
    )
    assert r["fetched"] == 7 and r["pool"] == 5 and r["selected"] == 3 and r["created"] == 3
    assert (b.source_version or "").startswith("2026-09-30") and "random.Random(7)" in (b.sampling_method or "")
    assert b.candidate_count == 3
    # 同批次重复同步：相同种子 → 全部跳过
    r2 = service.sync_fsa(db, b, 106, 1, True, 3, 7, "tester", transport=_transport(n=7, awaiting=2))
    assert r2["created"] == 0 and r2["skipped"] == 3
    # 另一批次全量：3 家关联、2 家新建（排除 2 家待检查）
    create_batch(client, "b2")
    b2 = db.scalar(select(Batch).where(Batch.batch_key == "b2"))
    r3 = service.sync_fsa(db, b2, 106, 1, True, None, None, "tester", transport=_transport(n=7, awaiting=2))
    assert r3["created"] == 2 and r3["linked"] == 3 and len(client.get("/api/leads").json()) == 5


def test_sync_endpoint_reports_upstream_failure(client, db, monkeypatch):
    login(client, db)
    create_batch(client, "b1")
    monkeypatch.setattr(fsa, "fetch_establishments", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    r = client.post("/api/batches/b1/sync/fsa", json={"authority_id": 106})
    assert r.status_code == 502 and "FSA" in r.json()["detail"]
    assert client.post("/api/batches/nope/sync/fsa", json={"authority_id": 106}).status_code == 404
