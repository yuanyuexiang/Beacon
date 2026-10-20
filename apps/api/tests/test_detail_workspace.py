"""单家销售工作区读取、版本保护和批量菜单资料；不调用真实模型或外部站点。"""

import uuid

from sqlalchemy import func, select

from app.modules.leads.models import Lead
from app.modules.menus.models import AnalysisStatus, FetchStatus, MenuAnalysis, MenuAsset
from app.modules.sales import contacts
from app.modules.sales.preparation import Preparation
from tests.test_assets import setup_lead
from tests.test_assignment import assign, person
from tests.test_users import session


def test_read_workspace_does_not_create_draft(client, db):
    identity = setup_lead(client, db)
    detail = client.get(f"/api/leads/{identity}").json()
    listed = client.get("/api/leads").json()[0]
    assert detail["communication_progress"] == listed["communication_progress"]
    assert detail["list_summary"] == listed["list_summary"]
    assert client.get(f"/api/communication/leads/{identity}").json()["drafts"] == []
    assert db.scalar(select(func.count()).select_from(Preparation)) == 0
    assert client.get(f"/api/leads/{identity}/menu-workspace").json() == {"assets": [], "analyses": {}}


def test_stale_website_save_rejected_but_other_fields_are_editable(client, db):
    identity = setup_lead(client, db)
    lead = db.get(Lead, uuid.UUID(identity))
    lead.website = "https://current.example"
    db.commit()
    response = client.patch(
        f"/api/leads/{identity}", json={"website": "https://stale.example", "expected_website": None}
    )
    assert response.status_code == 409
    assert client.get(f"/api/leads/{identity}").json()["website"] == "https://current.example"
    assert client.patch(f"/api/leads/{identity}", json={"screening_reason": "人工判断"}).status_code == 200
    response = client.patch(
        f"/api/leads/{identity}",
        json={"website": "https://chosen.example", "expected_website": "https://current.example"},
    )
    assert response.status_code == 200
    assert response.json()["website"] == "https://chosen.example"


def test_menu_workspace_retains_all_versions_grouped_by_file(client, db):
    identity = setup_lead(client, db)
    asset = MenuAsset(lead_id=uuid.UUID(identity), fetch_status=FetchStatus.fetched)
    db.add(asset)
    db.flush()
    for version in (1, 2):
        db.add(MenuAnalysis(asset_id=asset.id, version=version, engine="rules", status=AnalysisStatus.needs_review))
    db.commit()
    response = client.get(f"/api/leads/{identity}/menu-workspace")
    assert response.status_code == 200
    assert [x["version"] for x in response.json()["analyses"][str(asset.id)]] == [1, 2]
    assert len(response.json()["assets"]) == 1


def test_reassess_existing_evidence_does_not_scan_or_call_ai(client, db, monkeypatch):
    identity = setup_lead(client, db)
    monkeypatch.setattr(
        contacts, "review_contacts", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not scan"))
    )
    result = client.post(f"/api/leads/{identity}/auto-admission?refresh=false")
    assert result.status_code == 200
    assert result.json()["ai"] is None


def test_workspace_respects_lead_assignment(client, db):
    identity = setup_lead(client, db)
    boss = session(person(db, "boss", "director"))
    alice = session(person(db, "alice", "member"))
    bob = session(person(db, "bob", "member"))
    assign(boss, identity, "alice")
    assert alice.get(f"/api/leads/{identity}/menu-workspace").status_code == 200
    assert bob.get(f"/api/leads/{identity}/menu-workspace").status_code == 404
    assert bob.get(f"/api/communication/leads/{identity}").status_code == 404
