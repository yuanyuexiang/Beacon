import uuid

from sqlalchemy import func, select

from app.modules.leads.models import BatchLead, Lead
from app.modules.sales.models import ChannelEligibility
from tests.test_assignment import person
from tests.test_imports import login
from tests.test_users import session


def payload(**kw):
    return {"request_id": str(uuid.uuid4()), "name": "Rose Garden", **kw}


def test_create_minimal_idempotent_and_manual_website(client, db):
    login(client, db)
    body = payload(
        website="www.rose.example",
        contacts=[{"channel": "email", "contact_ref": "Owner@rose.example"}],
        notes="Met at a fair",
        contact_name="Jane",
    )
    r = client.post("/api/leads/manual", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    lead = db.get(Lead, data["id"])
    assert lead.assigned_to == "tester"
    assert lead.website == "https://www.rose.example"
    assert lead.raw["website_manual"]
    assert db.scalar(select(BatchLead.id).where(BatchLead.lead_id == lead.id))
    assert db.scalar(select(ChannelEligibility.contact_ref)) == "owner@rose.example"
    again = client.post("/api/leads/manual", json=body)
    assert again.json()["id"] == data["id"]
    assert db.scalar(select(func.count()).select_from(Lead)) == 1
    detail = client.get(f"/api/leads/{lead.id}").json()
    assert detail["manual_entry"]["contact_name"] == "Jane"
    assert "request_hash" not in detail["manual_entry"]
    body["name"] = "Changed"
    assert client.post("/api/leads/manual", json=body).status_code == 409


def test_duplicate_warns_but_allows_separate_branch(client, db):
    login(client, db)
    client.post("/api/leads/manual", json=payload())
    body = payload(address="A different branch")
    check = client.post("/api/leads/manual/check", json=body)
    assert len(check.json()["duplicates"]) == 1
    assert client.post("/api/leads/manual", json=body).status_code == 409
    body["allow_duplicate"] = True
    assert client.post("/api/leads/manual", json=body).status_code == 201
    assert db.scalar(select(func.count()).select_from(Lead)) == 2


def test_validation_is_atomic(client, db):
    login(client, db)
    assert client.post("/api/leads/manual", json=payload(name="   ")).status_code == 422
    assert client.post("/api/leads/manual", json=payload(website="javascript:alert(1)")).status_code == 422
    assert (
        client.post(
            "/api/leads/manual", json=payload(contacts=[{"channel": "email", "contact_ref": "bad"}])
        ).status_code
        == 422
    )
    assert client.post("/api/leads/manual", json=payload(batch_key="missing")).status_code == 404
    assert db.scalar(select(func.count()).select_from(Lead)) == 0


def test_member_scope_and_viewer(client, db):
    login(client, db)
    existing = client.post("/api/leads/manual", json=payload()).json()
    alice = session(person(db, "alice", "member"))
    body = payload()
    assert alice.post("/api/leads/manual/check", json=body).json()["duplicates"] == []
    assert alice.post("/api/leads/manual", json={**body, "assigned_to": "tester"}).status_code == 403
    assert alice.post("/api/leads/manual", json={**body, "batch_key": existing["batch_key"]}).status_code == 404
    r = alice.post("/api/leads/manual", json=body)
    assert r.status_code == 201, r.text
    assert alice.get(f"/api/leads/{r.json()['id']}").status_code == 200
    assert alice.get("/api/batches").json()
    viewer = session(person(db, "observer", "viewer"))
    assert viewer.post("/api/leads/manual", json=payload()).status_code == 403


def test_selected_batch_enrichment_and_domain_precision(client, db):
    login(client, db)
    first = client.post("/api/leads/manual", json=payload(website="https://notrose.example")).json()
    check = client.post("/api/leads/manual/check", json=payload(name="Different", website="https://rose.example"))
    assert check.json()["duplicates"] == []
    second = client.post("/api/leads/manual", json=payload(name="Second", batch_key=first["batch_key"]))
    assert second.status_code == 201, second.text
    assert second.json()["batch_key"] == first["batch_key"]
    task = client.post(
        f"/api/leads/{second.json()['id']}/enrichment", json={"mode": "continue", "items": ["website", "contacts"]}
    )
    assert task.status_code in (200, 201, 202), task.text
    blocked = client.post("/api/leads/manual", json=payload(name="Third", batch_key=first["batch_key"]))
    assert blocked.status_code == 409
    assert db.scalar(select(func.count()).select_from(Lead)) == 2
