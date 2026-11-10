"""Contact-scoped drafts and operator read positions; preserve all historical messages."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d182a0010001"
down_revision = "d181a0010001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("social_conversation_event", sa.Column("body_text", sa.Text(), nullable=True))
    op.drop_index("uq_communication_active", table_name="communication_draft")
    op.create_index(
        "uq_communication_active",
        "communication_draft",
        ["lead_id", "channel", "eligibility_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft' AND eligibility_id IS NOT NULL"),
    )
    op.create_index(
        "uq_communication_unselected",
        "communication_draft",
        ["lead_id", "channel"],
        unique=True,
        postgresql_where=sa.text("status = 'draft' AND eligibility_id IS NULL"),
    )
    op.create_table(
        "communication_read",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("operator", sa.String(64), sa.ForeignKey("operator.username", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", UUID(), sa.ForeignKey("lead.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_key", sa.String(64), nullable=False),
        sa.Column("read_through", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("operator", "lead_id", "contact_key", name="uq_communication_read"),
    )


def downgrade():
    op.drop_column("social_conversation_event", "body_text")
    # Old releases can represent only one active draft per channel. Preserve extras as cancelled history.
    op.execute("""UPDATE communication_draft SET status='cancelled' WHERE id IN (
        SELECT id FROM (SELECT id, row_number() OVER (
            PARTITION BY lead_id, channel ORDER BY updated_at DESC, id) AS n
            FROM communication_draft WHERE status='draft') ranked WHERE n > 1)""")
    op.drop_table("communication_read")
    op.drop_index("uq_communication_unselected", table_name="communication_draft")
    op.drop_index("uq_communication_active", table_name="communication_draft")
    op.create_index(
        "uq_communication_active",
        "communication_draft",
        ["lead_id", "channel"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
