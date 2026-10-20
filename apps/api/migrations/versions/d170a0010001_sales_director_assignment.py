"""Add sales director and lead ownership; historical leads remain unassigned."""

from alembic import op
import sqlalchemy as sa

revision = "d170a0010001"
down_revision = "d161a0010001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_operator_role", "operator", type_="check")
    op.create_check_constraint("ck_operator_role", "operator", "role IN ('admin', 'director', 'member', 'viewer')")
    op.add_column("lead", sa.Column("assigned_to", sa.String(64), nullable=True))
    op.create_foreign_key("fk_lead_owner", "lead", "operator", ["assigned_to"], ["username"], ondelete="SET NULL")
    op.create_index("ix_lead_assigned_to", "lead", ["assigned_to"])


def downgrade():
    op.drop_index("ix_lead_assigned_to", "lead")
    op.drop_constraint("fk_lead_owner", "lead", type_="foreignkey")
    op.drop_column("lead", "assigned_to")
    op.execute("UPDATE operator SET role='member', session_version=session_version+1 WHERE role='director'")
    op.drop_constraint("ck_operator_role", "operator", type_="check")
    op.create_check_constraint("ck_operator_role", "operator", "role IN ('admin', 'member', 'viewer')")
