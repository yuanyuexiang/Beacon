"""Persist social account connection diagnostics without credentials."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d177a0010001"
down_revision = "d176a0010001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("channel_account", sa.Column("connection_diagnostics", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("channel_account", "connection_diagnostics")
