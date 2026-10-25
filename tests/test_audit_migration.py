import time
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from alembic import command
from alembic.config import Config
from backend import db


def test_backfill_preserves_history_and_financial_records(tmp_path, monkeypatch):
    engine = sa.create_engine('sqlite:///'+str(tmp_path/'migration.db'))
    monkeypatch.setattr(db, 'engine', engine)
    cfg = Config('alembic.ini')
    command.upgrade(cfg, '7c2ef24a90be')
    factory = sessionmaker(engine)
    with factory.begin() as session:
        for mode, source in [('preview','fixture'),('sandbox','paypal_sandbox')]:
            session.add(db.Payment(id=mode+'-payment',order_id=mode+'-order',capture_id=mode+'-capture',source=source,amount_cents=2000,status='COMPLETED'))
            session.flush()
            session.add(db.Case(id=mode+'-case',payment_id=mode+'-payment',statement='A fictional damaged item.',requested_cents=500))
            session.flush()
            session.add(db.Proposal(id=mode+'-proposal',case_id=mode+'-case',decision='refund',amount_cents=500,explanation='A historical recommendation.',source='historical-model',policy_hash='hash',payment_version=1,fingerprint='fingerprint'))
            session.flush()
            session.add(db.Refund(id=mode+'-refund',proposal_id=mode+'-proposal',payment_id=mode+'-payment',amount_cents=500,payload={}))
        session.add(db.Webhook(event_id='verified-event',event_type='PAYMENT.CAPTURE.REFUNDED',payload={}))
    with engine.begin() as connection:
        history = sa.Table('audit',sa.MetaData(),autoload_with=connection)
        events = [
            ('preview-case-event','preview-case',{}),
            ('sandbox-case-event','sandbox-case',{}),
            ('preview-refund-event',None,{'operation_id':'preview-refund'}),
            ('sandbox-payment-event',None,{'payment_id':'sandbox-payment'}),
            ('sandbox-proposal-event',None,{'proposal_id':'sandbox-proposal'}),
            ('preview-source-event',None,{'source':'rule_based_preview'}),
            ('preview-provider-event',None,{'provider_refund_id':'PREVIEW-old-refund'}),
            ('sandbox-webhook-event',None,{'event_id':'verified-event'}),
            ('unclassified-event',None,{}),
        ]
        connection.execute(history.insert(),[{'id':name,'action':name,'case_id':case,'details':details,'created_at':time.time()} for name,case,details in events])
    command.upgrade(cfg, 'head')
    command.check(cfg)
    def verify():
        with engine.connect() as connection:
            history = sa.Table('audit',sa.MetaData(),autoload_with=connection)
            labels = dict(connection.execute(sa.select(history.c.id,history.c.environment)).all())
            assert len(labels)==9
            for key,value in labels.items():
                assert value == ('preview' if key.startswith('preview') else 'sandbox' if key.startswith('sandbox') else 'legacy')
            assert connection.execute(sa.text('SELECT SUM(amount_cents) FROM payments')).scalar()==4000
            assert connection.execute(sa.text('SELECT SUM(amount_cents) FROM refunds')).scalar()==1000
    verify()
    command.downgrade(cfg,'7c2ef24a90be')
    command.upgrade(cfg,'head')
    verify()
    engine.dispose()
