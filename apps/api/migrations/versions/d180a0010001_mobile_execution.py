"""Add paired phone execution, immutable confirmation and durable results."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "d180a0010001"
down_revision = "d179a0010001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mobile_device",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner", sa.String(64), sa.ForeignKey("operator.username", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("account", sa.String(64)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("capabilities", JSONB(), nullable=False),
    )
    op.create_table(
        "mobile_pairing",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("owner", sa.String(64), sa.ForeignKey("operator.username", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "mobile_execution",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("task_id", UUID(), sa.ForeignKey("manual_task.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("lead_id", UUID(), sa.ForeignKey("lead.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", UUID(), sa.ForeignKey("mobile_device.id"), nullable=False),
        sa.Column("confirmed_by", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_hash", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result", JSONB()),
        sa.Column("error", sa.Text()),
    )


def downgrade():
    op.drop_table("mobile_execution")
    op.drop_table("mobile_pairing")
    op.drop_table("mobile_device")
