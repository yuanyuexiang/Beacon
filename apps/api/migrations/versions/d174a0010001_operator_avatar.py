"""Store normalized user avatar thumbnails with database backups."""

from alembic import op
import sqlalchemy as sa

revision = "d174a0010001"
down_revision = "d170a0010001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("operator", sa.Column("avatar_data", sa.LargeBinary(), nullable=True))
    op.add_column("operator", sa.Column("avatar_version", sa.String(32), nullable=True))


def downgrade():
    op.drop_column("operator", "avatar_version")
    op.drop_column("operator", "avatar_data")
