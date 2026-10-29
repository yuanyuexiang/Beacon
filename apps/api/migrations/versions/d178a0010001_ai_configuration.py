"""Versioned encrypted AI connections and task routing."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d178a0010001"
down_revision = "d177a0010001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_configuration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
    )


def downgrade():
    op.drop_table("ai_configuration")
