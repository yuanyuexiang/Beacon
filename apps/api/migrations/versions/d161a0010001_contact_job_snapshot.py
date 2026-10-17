"""Persist per-job contact read snapshots."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d161a0010001"
down_revision = "d160a0010001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("batch_job", sa.Column("contact_result", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("batch_job", "contact_result")
