"""Serialize model analysis per request across clients."""
from alembic import op
import sqlalchemy as sa
revision = "e81d6a45f902"
down_revision = "c34f87b2e641"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("analysis_leases",
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), primary_key=True),
        sa.Column("token", sa.String(36), nullable=True),
        sa.Column("expires_at", sa.Float(), nullable=False))

def downgrade():
    op.drop_table("analysis_leases")
