"""Persist resumable list workflows.

Revision ID: da54a0010001
Revises: f9496c930a01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "da54a0010001"
down_revision = "f9496c930a01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "list_workflow",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batch.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("contact_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batch_run.id", ondelete="SET NULL")),
        sa.Column("started_by", sa.String(64), nullable=False),
    )
    op.create_index("ix_list_workflow_batch_id", "list_workflow", ["batch_id"])


def downgrade() -> None:
    op.drop_table("list_workflow")
