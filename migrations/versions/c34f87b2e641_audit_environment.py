"""Scope audit history by payment environment, retaining unclassified legacy events.

Revision ID: c34f87b2e641
Revises: 7c2ef24a90be
"""
from alembic import op
import sqlalchemy as sa

revision = "c34f87b2e641"
down_revision = "7c2ef24a90be"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit", sa.Column("environment", sa.String(20), server_default="legacy", nullable=False))
    bind = op.get_bind()
    metadata = sa.MetaData()
    tables = {name: sa.Table(name, metadata, autoload_with=bind) for name in ("audit", "payments", "cases", "refunds", "proposals", "webhooks")}
    payments = dict(bind.execute(sa.select(tables["payments"].c.id, tables["payments"].c.source)).all())
    cases = dict(bind.execute(sa.select(tables["cases"].c.id, tables["cases"].c.payment_id)).all())
    refunds = dict(bind.execute(sa.select(tables["refunds"].c.id, tables["refunds"].c.payment_id)).all())
    proposals = dict(bind.execute(sa.select(tables["proposals"].c.id, tables["proposals"].c.case_id)).all())
    webhooks = set(bind.execute(sa.select(tables["webhooks"].c.event_id)).scalars())
    history = tables["audit"]
    for row in bind.execute(sa.select(history.c.id, history.c.case_id, history.c.details)).mappings():
        details = row["details"] or {}
        payment_id = (cases.get(row["case_id"]) or details.get("payment_id") or refunds.get(details.get("operation_id"))
                      or cases.get(proposals.get(details.get("proposal_id"))))
        source = payments.get(payment_id) or details.get("source")
        environment = {"fixture": "preview", "paypal_sandbox": "sandbox", "rule_based_preview": "preview"}.get(source)
        if environment is None and str(details.get("provider_refund_id", "")).startswith("PREVIEW-"):
            environment = "preview"
        if environment is None and details.get("event_id") in webhooks:
            environment = "sandbox"
        if environment:
            bind.execute(history.update().where(history.c.id == row["id"]).values(environment=environment))
    op.create_index("ix_audit_environment", "audit", ["environment"])


def downgrade():
    op.drop_index("ix_audit_environment", table_name="audit")
    op.drop_column("audit", "environment")
