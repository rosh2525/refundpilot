"""Optional normalized case evidence, visual assessment, and merchant estimates.

Revision ID: 7c2ef24a90be
Revises: 143a49704b62
"""
from alembic import op
import sqlalchemy as sa

revision = "7c2ef24a90be"
down_revision = "143a49704b62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("return_shipping_cents", sa.Integer(), nullable=True))
    op.add_column("cases", sa.Column("restocking_cents", sa.Integer(), nullable=True))
    op.add_column("proposals", sa.Column("visual_assessment", sa.JSON(), nullable=True))
    op.add_column("proposals", sa.Column("evidence_sha256", sa.String(64), nullable=True))
    op.create_table(
        "case_evidence",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("image_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("mime_type", sa.String(30), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id"),
    )


def downgrade() -> None:
    op.drop_table("case_evidence")
    op.drop_column("proposals", "evidence_sha256")
    op.drop_column("proposals", "visual_assessment")
    op.drop_column("cases", "restocking_cents")
    op.drop_column("cases", "return_shipping_cents")
