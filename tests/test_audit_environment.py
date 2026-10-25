import asyncio
from sqlalchemy import select
from backend.config import settings
from backend.db import Audit, Payment, Session, audit
from backend.worker import run_once
from .conftest import approved_refund


def test_dashboard_filters_environment_before_latest_event_limit(client, payment, monkeypatch):
    approved_refund(client, payment)
    asyncio.run(run_once())
    with Session.begin() as session:
        sandbox = Payment(order_id='sandbox-order', capture_id='sandbox-capture', source='paypal_sandbox', amount_cents=2000, status='COMPLETED')
        session.add(sandbox); session.flush()
        audit(session, 'payment_captured', payment_id=sandbox.id)
        # More recent preview events must not displace the sandbox event.
        for _ in range(45):
            audit(session, 'preview_history', payment_id=payment['id'])
        session.add(Audit(action='unclassified_history', environment='legacy', details={}))
    monkeypatch.setattr(settings, 'mode', 'sandbox')
    dashboard = client.get('/api/dashboard').json()
    assert len(dashboard['audit']) == 1
    assert dashboard['audit'][0]['environment'] == 'sandbox'
    assert dashboard['audit'][0]['action'] == 'payment_captured'
    assert not dashboard['refunds']
    assert all(p['source'] == 'paypal_sandbox' for p in dashboard['payments'])


def test_linked_payment_source_overrides_current_mode_for_audit(client, payment, monkeypatch):
    operation, case = approved_refund(client, payment)
    monkeypatch.setattr(settings, 'mode', 'sandbox')
    with Session.begin() as session:
        audit(session, 'case_event', case['id'])
        audit(session, 'operation_event', operation_id=operation['id'])
        audit(session, 'verified_webhook_received', environment='sandbox', event_id='verified-test-event')
    with Session() as session:
        events = {e.action:e.environment for e in session.scalars(select(Audit)).all()}
    assert events['case_event'] == events['operation_event'] == 'preview'
    assert events['verified_webhook_received'] == 'sandbox'
