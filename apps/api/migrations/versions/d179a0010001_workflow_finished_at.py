"""Record explicit completion timestamps without guessing historical values."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d179a0010001"
down_revision = "d178a0010001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("list_workflow", sa.Column("history_scope", postgresql.JSONB(), nullable=True))
    op.add_column("list_workflow", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("list_workflow", "history_scope")
    op.drop_column("list_workflow", "finished_at")
