"""Separate preparation todos and channel evidence from executable deliveries."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d176a0010001"
down_revision = "d174a0010001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("channel_eligibility", sa.Column("conditions", postgresql.JSONB(), nullable=True))
    op.add_column("communication_draft", sa.Column("queued", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    op.drop_column("communication_draft", "queued")
    op.drop_column("channel_eligibility", "conditions")
