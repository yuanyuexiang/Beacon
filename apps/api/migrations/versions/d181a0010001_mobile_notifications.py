"""Add phone reply notification inbox and explicitly linked conversations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d181a0010001"
down_revision = "d180a0010001"
branch_labels = None
depends_on = None


def base():
    return [
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("device_id", UUID(), sa.ForeignKey("mobile_device.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
    ]


def upgrade():
    op.create_table(
        "mobile_reply_notification",
        *base(),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("thread_key", sa.String(64)),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("structured", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("execution_id", UUID(), sa.ForeignKey("mobile_execution.id", ondelete="SET NULL")),
        sa.Column("event_id", UUID(), sa.ForeignKey("event.id", ondelete="SET NULL")),
        sa.UniqueConstraint("device_id", "event_key"),
    )
    op.create_index("ix_mobile_reply_inbox", "mobile_reply_notification", ["device_id", "status", "created_at"])
    op.create_table(
        "mobile_reply_thread",
        *base(),
        sa.Column("thread_key", sa.String(64), nullable=False),
        sa.Column("execution_id", UUID(), sa.ForeignKey("mobile_execution.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("device_id", "channel", "thread_key"),
    )


def downgrade():
    op.drop_table("mobile_reply_thread")
    op.drop_table("mobile_reply_notification")
