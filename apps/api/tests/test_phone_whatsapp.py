"""Phone conversion preserves independent channel decisions; never sends messages."""

import uuid

from app.modules.leads.models import Lead
from app.modules.sales.models import Suppression, SuppressionScope
from app.modules.sales.service import now
from tests.test_imports import login
from tests.test_sales import _elig


def phone(client, db):
    login(client, db)
    lead = Lead(source_key="manual:phone-whatsapp", source_name="manual", name="Phone test")
    db.add(lead)
    db.commit()
    response = _elig(client, str(lead.id), channel="phone", contact_ref="+447700900123")
    assert response.status_code == 200, response.text
    row = response.json()
    return lead, row, f"/api/leads/{lead.id}/eligibility/{row['id']}/whatsapp"


def test_conversion_deduplicates_and_keeps_channel_decisions(client, db):
    lead, source, path = phone(client, db)
    converted = client.post(path, json={"contact_ref": "0044 (7700) 900-123"})
    assert converted.status_code == 200, converted.text
    row = converted.json()
    assert row["contact_ref"] == "+447700900123"
    assert row["contact_usable"] == "unknown" and row["eligibility"] == "unknown"
    assert str(source["id"]) in row["contact_source"]
    approved = _elig(client, str(lead.id), channel="whatsapp", contact_ref=row["contact_ref"]).json()
    duplicate = client.post(path, json={"contact_ref": row["contact_ref"]}).json()
    assert duplicate["id"] == approved["id"] and duplicate["eligibility"] == "allowed"
    original = next(r for r in client.get(f"/api/leads/{lead.id}/eligibility").json() if r["id"] == source["id"])
    assert original["channel"] == "phone" and original["eligibility"] == "allowed"


def test_conversion_rejects_invalid_target_and_suppression(client, db):
    lead, _, path = phone(client, db)
    assert client.post(path, json={"contact_ref": "07700900123"}).status_code == 400
    wrong = f"/api/leads/{lead.id}/eligibility/{uuid.uuid4()}/whatsapp"
    assert client.post(wrong, json={"contact_ref": "+447700900123"}).status_code == 404
    db.add(Suppression(scope=SuppressionScope.contact, contact_ref="+447700900123", reason="manual", created_at=now()))
    db.commit()
    assert client.post(path, json={"contact_ref": "+447700900123"}).status_code == 409
