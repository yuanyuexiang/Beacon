"""销售名单摘要只用最新分析，读取不产生外部请求。"""

from sqlalchemy import select

from app.modules.leads.models import Lead
from app.modules.menus.models import AnalysisStatus, FetchStatus, MenuAnalysis, MenuAsset
from tests.test_imports import CSV_A, create_batch, login, upload


def test_list_menu_uses_latest_version_and_preserves_other_valid_file(client, db):
    login(client, db)
    create_batch(client)
    upload(client, "b1", CSV_A)
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))

    def summary():
        row = next(r for r in client.get("/api/leads?batch_key=b1").json() if r["id"] == str(lead.id))
        return row["list_summary"]

    assert summary() == {"menu_status": "missing", "channels": []}
    asset = MenuAsset(lead_id=lead.id, fetch_status=FetchStatus.fetched)
    db.add(asset)
    db.flush()
    db.add(
        MenuAnalysis(
            asset_id=asset.id, version=1, status=AnalysisStatus.succeeded, engine="rules", review_state="reviewed"
        )
    )
    db.commit()
    assert summary()["menu_status"] == "reviewed"
    db.add(MenuAnalysis(asset_id=asset.id, version=2, status=AnalysisStatus.needs_review, engine="rules"))
    db.commit()
    assert summary()["menu_status"] == "needs_review"
    other = MenuAsset(lead_id=lead.id, fetch_status=FetchStatus.failed)
    db.add(other)
    db.commit()
    assert summary()["menu_status"] == "needs_review"
    assert client.get("/api/leads?batch_key=b1").status_code == 200

    db.add(MenuAnalysis(asset_id=asset.id, version=3, status=AnalysisStatus.failed, engine="rules"))
    db.commit()
    assert summary()["menu_status"] == "analysis_failed"
    response = client.post(
        f"/api/leads/{lead.id}/contacts",
        json={
            "items": [{"channel": "email", "contact_ref": "hello@restaurant.example", "contact_source": "test fixture"}]
        },
    )
    assert response.status_code == 200
    assert summary()["channels"] == ["email"]
    response = client.post(
        f"/api/leads/{lead.id}/contacts",
        json={
            "items": [
                {"channel": "other_social", "contact_ref": "https://x.com/fixture", "contact_source": "test fixture"}
            ]
        },
    )
    assert response.status_code == 200
    assert summary()["channels"] == ["email", "X"]
