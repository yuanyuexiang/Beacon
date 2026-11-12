from app.modules.sales import contacts
from tests.test_contacts import _lead_id


def scan(url, *, ok=True, values=None):
    return {
        "url": url,
        "pages": [{"url": url, "ok": ok}],
        "contacts": values or [],
        "identity_documents": [{"id": "page0", "url": url, "text": "Contact us"}],
    }


def test_failed_primary_falls_back_and_reuses_success_without_losing_sources(client, db, monkeypatch):
    from app.modules.leads.models import Lead

    identity = _lead_id(
        client,
        db,
        website="https://current.example",
        overture={
            "matched": True,
            "websites": ["https://fallback.example", "https://fallback.example/"],
            "phones": ["01224 123456"],
            "socials": ["https://www.facebook.com/cafe"],
        },
    )
    lead = db.get(Lead, identity)
    lead.raw = {
        **lead.raw,
        "source_sync": {"candidates": [{"place_id": "g1", "website": lead.website, "phone": "+44 1224 123456"}]},
    }
    calls = []

    def read(url):
        calls.append(url)
        if url == lead.website:
            raise ValueError("network unavailable")
        return scan(url, values=[{"kind": "email", "value": "hello@fallback.example", "page_url": url}])

    monkeypatch.setattr(contacts, "scan_website", read)
    first = contacts.find_contacts(db, lead)
    assert calls == [lead.website, "https://fallback.example"]
    phone = next(c for c in first["candidates"] if c["kind"] == "phone")
    assert {s["type"] for s in phone["sources"]} == {"overture", "google_places"}
    assert any(c["kind"] == "email" for c in first["candidates"])
    assert len({d["id"] for d in first["website"]["identity_documents"]}) == 1
    lead.raw = {**lead.raw, "contact_source_scans": first["source_scans"]}
    calls.clear()
    second = contacts.find_contacts(db, lead)
    assert calls == [lead.website]  # retry failed source, reuse complete fallback
    assert second["candidates"] == first["candidates"]
    assert (
        second["source_scans"]["https://fallback.example"]["at"]
        == first["source_scans"]["https://fallback.example"]["at"]
    )
    assert lead.website == "https://current.example"
    monkeypatch.setattr(
        contacts,
        "scan_website",
        lambda url: scan(url, values=[{"kind": "phone", "value": "+441224123456", "page_url": url}]),
    )
    recovered = contacts.find_contacts(db, lead)
    assert any(c["kind"] == "email" for c in recovered["candidates"])  # cached fallback survives primary recovery


def test_complete_primary_does_not_scan_alternatives(client, db, monkeypatch):
    from app.modules.leads.models import Lead

    identity = _lead_id(
        client, db, website="https://manual.example", overture={"matched": True, "websites": ["https://old.example"]}
    )
    lead = db.get(Lead, identity)
    calls = []

    def read(url):
        calls.append(url)
        return scan(url, values=[{"kind": "phone", "value": "+441224123456", "page_url": url}])

    monkeypatch.setattr(contacts, "scan_website", read)
    contacts.find_contacts(db, lead)
    assert calls == [lead.website]


def test_source_contacts_survive_all_website_failures(client, db, monkeypatch):
    from app.modules.leads.models import Lead

    identity = _lead_id(
        client, db, website="https://offline.example", overture={"matched": True, "phones": ["01224 123456"]}
    )
    lead = db.get(Lead, identity)
    monkeypatch.setattr(contacts, "scan_website", lambda _: scan(lead.website, ok=False))
    result = contacts.find_contacts(db, lead)
    assert result["candidates"][0]["value"] == "+441224123456"
    assert result["website"]["pages"][0]["ok"] is False


def test_social_website_itself_is_a_contact_even_when_page_has_no_links(client, db, monkeypatch):
    from app.modules.leads.models import Lead

    url = "https://www.instagram.com/lilybank.bakehouse"
    identity = _lead_id(client, db, website=url)
    lead = db.get(Lead, identity)
    monkeypatch.setattr(contacts, "scan_website", lambda address: scan(address))
    result = contacts.collect(db, lead)
    db.commit()
    assert result["found"] == 1
    rows = client.get(f"/api/leads/{identity}/eligibility").json()
    assert len(rows) == 1
    assert rows[0]["channel"] == "instagram"
    assert "lilybank.bakehouse" in rows[0]["contact_ref"]


def test_read_completed_without_contacts_still_needs_enrichment(client, db):
    from app.modules.leads import enrichment
    from app.modules.leads.models import Lead
    from app.modules.sales import service

    identity = _lead_id(client, db)
    lead = db.get(Lead, identity)
    lead.raw = {
        **lead.raw,
        "contacts_scan": {
            "at": service.now().isoformat(),
            "found": 0,
            "website": lead.website,
            "pages_ok": 1,
            "pages_failed": 0,
            "ai_status": "completed",
            "ranking_version": contacts.contact_ranking.VERSION,
        },
    }
    item = next(i for i in enrichment.items(db, lead) if i["key"] == "contacts")
    assert item["needed"] is True
