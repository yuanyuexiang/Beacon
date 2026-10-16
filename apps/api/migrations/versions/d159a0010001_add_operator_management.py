"""Add operator roles and revocable sessions.

Revision ID: d159a0010001
Revises: d157a0010001
"""

from alembic import op
import sqlalchemy as sa

revision = "d159a0010001"
down_revision = "d157a0010001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operator", sa.Column("display_name", sa.String(80), nullable=True))
    op.add_column("operator", sa.Column("role", sa.String(16), server_default="member", nullable=False))
    op.add_column("operator", sa.Column("session_version", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "operator", sa.Column("must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.execute("UPDATE operator SET role = 'admin'")
    op.create_check_constraint("ck_operator_role", "operator", "role IN ('admin', 'member', 'viewer')")


def downgrade() -> None:
    op.drop_constraint("ck_operator_role", "operator", type_="check")
    for column in ("must_change_password", "session_version", "role", "display_name"):
        op.drop_column("operator", column)
