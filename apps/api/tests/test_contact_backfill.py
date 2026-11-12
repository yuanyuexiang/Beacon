import importlib.util
from pathlib import Path

from sqlalchemy import select

from app.modules.leads.models import Lead
from app.modules.sales.models import ChannelEligibility, Eligibility


def test_saved_candidates_backfill_is_idempotent(db, monkeypatch):
    lead = Lead(
        name="Saved contacts",
        source_key="manual:backfill-test",
        source_name="manual",
        raw={
            "contact_review": {
                "candidates": [
                    {"channel": "email", "value": "hello@example.com", "sources": [{"ref": "https://example.com"}]},
                    {"channel": "phone", "value": "+441234567890", "suppressed": True},
                ]
            }
        },
    )
    db.add(lead)
    db.flush()
    path = Path(__file__).parents[1] / "migrations/versions/d183a0010001_restore_discovered_contacts.py"
    spec = importlib.util.spec_from_file_location("contact_backfill", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration.op, "get_bind", db.connection)
    migration.upgrade()
    migration.upgrade()
    rows = list(db.scalars(select(ChannelEligibility).where(ChannelEligibility.lead_id == lead.id)))
    assert len(rows) == 1
    assert rows[0].contact_ref == "hello@example.com"
    assert rows[0].eligibility == Eligibility.unknown
