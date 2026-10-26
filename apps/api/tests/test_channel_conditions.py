from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.sales import channel_conditions as cc
from app.modules.sales import service
from app.modules.sales.models import Channel, ChannelEligibility, Eligibility, ManualTask
from tests.test_assets import setup_lead
from tests.test_communication import activate, prepare
from tests.test_sales import _ready


def review(channel):
    at = datetime.now(UTC)
    return {
        "decision": "allowed",
        "confirmed": True,
        "note": "Reviewed for menu business outreach",
        "evidence": [
            {
                "key": r["key"],
                "source": "record:test",
                "detail": "Verified evidence from the business record",
                "checked_at": (at - timedelta(minutes=1)).isoformat(),
                "expires_at": (at + timedelta(days=7)).isoformat(),
                "result": "clear" if channel == "phone" else "verified",
            }
            for r in cc.REQUIREMENTS[channel]
        ],
    }


@pytest.mark.parametrize("channel", list(cc.REQUIREMENTS))
def test_channel_review_requires_specific_evidence_and_expiry(client, db, channel):
    identity = setup_lead(client, db)
    row = ChannelEligibility(lead_id=identity, channel=Channel(channel), contact_ref="contact:test")
    db.add(row)
    db.commit()
    url = f"/api/leads/{identity}/contacts/{row.id}/conditions"
    assert client.get(url).json()["requirements"] == cc.REQUIREMENTS[channel]
    body = review(channel)
    assert client.post(url, json={**body, "evidence": []}).status_code == 422
    assert client.post(url, json={**body, "confirmed": False}).status_code == 422
    assert client.post(url, json=body).status_code == 200
    db.refresh(row)
    assert row.eligibility == Eligibility.allowed
    assert row.conditions is not None
    assert row.conditions["reviewed_by"] == "tester"
    assert client.get(url).json()["missing"] == []
    row.conditions = {
        **row.conditions,
        "evidence": [{**e, "expires_at": "2020-01-01T00:00:00+00:00"} for e in row.conditions["evidence"]],
    }
    db.commit()
    assert client.get(url).json()["status"] == "unknown"
    assert not db.scalar(select(ManualTask.id))


def test_phone_screening_cannot_be_guessed_or_extended():
    record = {**review("phone"), "version": cc.VERSION, "purpose": "business_marketing"}
    record["evidence"][0]["result"] = "verified"
    assert cc.missing("phone", record)
    record["evidence"][0]["result"] = "clear"
    record["evidence"][0]["expires_at"] = (datetime.now(UTC) + timedelta(days=60)).isoformat()
    assert any("28" in e for e in cc.missing("phone", record))


def test_preparation_todo_is_explicit_reversible_and_never_executable(client, db):
    identity = setup_lead(client, db)
    draft = prepare(client, identity)["draft"]
    assert client.get("/api/communication/overview").json()["total"] == 0
    url = f"/api/communication/drafts/{draft['id']}"
    result = client.patch(url, json={"queued": True})
    assert result.status_code == 200 and result.json()["blockers"]
    assert client.get("/api/communication/overview?channel=email").json()["total"] == 1
    assert client.get("/api/communication/overview?channel=phone").json()["total"] == 0
    assert "error" in activate(client, draft["id"])
    assert client.get(f"/api/tasks?lead_id={identity}").json() == []
    client.patch(url, json={"queued": False})
    assert client.get("/api/communication/overview").json()["total"] == 0


def test_send_gate_rechecks_structured_record_even_if_old_api_sets_allowed(client, db):
    from app.modules.content.models import ContentPiece

    identity, _, content_id = _ready(client, db)
    row = ChannelEligibility(
        lead_id=identity, channel=Channel.email, contact_ref="info@example.org", eligibility=Eligibility.allowed
    )
    row.conditions = {**review("email"), "version": cc.VERSION, "purpose": "business_marketing", "evidence": []}
    db.add(row)
    db.commit()
    db.refresh(row)
    with pytest.raises(service.SalesError, match="缺少"):
        service.check_can_contact(db, row, db.get(ContentPiece, content_id["id"]))


def test_missing_evidence_can_be_saved_for_later(client, db):
    identity = setup_lead(client, db)
    row = ChannelEligibility(lead_id=identity, channel=Channel.phone)
    db.add(row)
    db.commit()
    response = client.post(
        f"/api/leads/{identity}/contacts/{row.id}/conditions",
        json={"decision": "unknown", "note": "Await screening", "evidence": [{"key": "tps", "source": "pending"}]},
    )
    assert response.status_code == 200 and response.json()["missing"]


def test_requested_reply_is_bound_to_confirmed_content(client, db):
    from app.modules.content.models import ContentPiece

    identity, _, content = _ready(client, db)
    row = ChannelEligibility(lead_id=identity, channel=Channel.email, contact_ref="info@example.org")
    db.add(row)
    db.commit()
    body = review("email")
    body.update(purpose="requested_reply", content_id=content["id"])
    body["evidence"][0]["key"] = "inbound_request"
    url = f"/api/leads/{identity}/contacts/{row.id}/conditions"
    assert client.post(url, json={**body, "content_id": None}).status_code == 422
    assert client.post(url, json=body).status_code == 200
    db.refresh(row)
    piece = db.get(ContentPiece, content["id"])
    assert cc.content_missing(row.conditions, str(piece.id), piece.content_hash) == []
    assert cc.content_missing(row.conditions, str(piece.id), "changed")
    assert cc.content_missing(row.conditions, "another", piece.content_hash)


def test_postal_address_is_not_a_browser_url():
    from app.modules.sales.workbench import manual_target

    assert manual_target("post", "12 High Street, Aberdeen AB1 1AA") == "#postal-address"
    assert manual_target("post", "https://example.org") is None
