"""Expose saved source contacts independently of AI recommendations."""

import uuid

from alembic import op
import sqlalchemy as sa

revision = "d183a0010001"
down_revision = "d182a0010001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # No network or AI calls; preserve every existing contact and its decisions.
    rows = (
        connection.execute(
            sa.text("""
        SELECT l.id AS lead_id, c AS candidate
        FROM lead l CROSS JOIN LATERAL jsonb_array_elements(
            CASE WHEN jsonb_typeof(l.raw->'contact_review'->'candidates') = 'array'
            THEN l.raw->'contact_review'->'candidates' ELSE '[]'::jsonb END) c
    """)
        )
        .mappings()
        .all()
    )
    for row in rows:
        candidate = row["candidate"]
        channel = candidate.get("channel")
        value = (candidate.get("value") or "").strip()
        if channel not in {
            "email",
            "phone",
            "whatsapp",
            "facebook",
            "instagram",
            "linkedin",
            "tiktok",
            "other_social",
            "contact_form",
        }:
            continue
        if not value or len(value) > 256 or candidate.get("suppressed"):
            continue
        sources = "；".join(str(s.get("ref") or "") for s in candidate.get("sources", []) if isinstance(s, dict))[:256]
        connection.execute(
            sa.text("""
            INSERT INTO channel_eligibility
                (id, lead_id, channel, contact_ref, contact_source, contact_collected_at,
                 contact_usable, eligibility)
            SELECT :id, :lead, CAST(:channel AS varchar), CAST(:value AS varchar), :source, now(), 'unknown', 'unknown'
            WHERE NOT EXISTS (SELECT 1 FROM channel_eligibility
                WHERE lead_id=:lead AND channel=CAST(:channel AS varchar) AND contact_ref=CAST(:value AS varchar))
        """),
            {"id": uuid.uuid4(), "lead": row["lead_id"], "channel": channel, "value": value, "source": sources or None},
        )


def downgrade():
    # Contacts are user data: never delete them when rolling back code.
    pass
