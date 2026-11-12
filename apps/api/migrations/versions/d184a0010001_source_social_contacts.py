"""Preserve social profiles stored as source websites as contact channels."""

import uuid
from urllib.parse import urlparse

from alembic import op
import sqlalchemy as sa

revision = "d184a0010001"
down_revision = "d183a0010001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, website, raw FROM lead")).mappings().all()
    hosts = {
        "instagram.com": "instagram",
        "facebook.com": "facebook",
        "fb.com": "facebook",
        "linkedin.com": "linkedin",
        "tiktok.com": "tiktok",
        "youtube.com": "other_social",
        "youtu.be": "other_social",
        "x.com": "other_social",
        "twitter.com": "other_social",
    }
    for row in rows:
        raw = row["raw"] or {}
        urls = [row["website"]]
        urls.extend(c.get("website") for c in (raw.get("source_sync") or {}).get("candidates", []))
        ov = raw.get("overture") or {}
        if ov.get("matched"):
            urls.extend(ov.get("websites") or [])
        for url in dict.fromkeys(urls):
            if not isinstance(url, str) or len(url) > 256:
                continue
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
            channel = hosts.get(host)
            if not channel or not parsed.path.strip("/") or parsed.scheme not in {"http", "https"}:
                continue
            connection.execute(
                sa.text("""
                INSERT INTO channel_eligibility
                    (id, lead_id, channel, contact_ref, contact_source, contact_collected_at, contact_usable, eligibility)
                SELECT :id, :lead, CAST(:channel AS varchar), CAST(:value AS varchar), :source, now(), 'unknown', 'unknown'
                WHERE NOT EXISTS (SELECT 1 FROM channel_eligibility
                    WHERE lead_id=:lead AND channel=CAST(:channel AS varchar) AND contact_ref=CAST(:value AS varchar))
            """),
                {
                    "id": uuid.uuid4(),
                    "lead": row["id"],
                    "channel": channel,
                    "value": url,
                    "source": f"来源网站 {url}"[:256],
                },
            )


def downgrade():
    # Preserve contact records and any subsequent user decisions.
    pass
