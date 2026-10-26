import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from backend import main
from backend.ai import AIUnavailable
from backend.config import settings
from backend.db import Session, AnalysisLease, Payment, Proposal, Refund, Quota, Case, Audit
from .conftest import reviewed_case


def test_stale_projection_and_recovery_preserve_proposal_history(client, payment):
    case = reviewed_case(client, payment)
    proposal = case['proposal']
    assert proposal['can_approve']
    with Session.begin() as session:
        p = session.get(Payment, payment['id'])
        p.version += 1
        p.refunded_cents = 100
    current = next(c for c in client.get('/api/dashboard').json()['cases'] if c['id'] == case['id'])
    assert current['proposal']['state'] == 'stale'
    assert not current['proposal']['can_approve']
    assert current['proposal']['current_issues']
    assert client.post(f"/api/proposals/{proposal['id']}/approve", json={'confirmed':True,'fingerprint':proposal['fingerprint']}).status_code == 409
    with Session() as session:
        assert session.get(Proposal, proposal['id']).state == 'ready'
        assert session.scalar(select(func.count()).select_from(Refund)) == 0
    refreshed = client.post(f"/api/cases/{case['id']}/analyze").json()
    assert refreshed['proposal']['can_approve']
    assert refreshed['proposal']['id'] != proposal['id']


@pytest.mark.parametrize('change', ['policy','evidence','balance','window','fingerprint'])
def test_current_eligibility_covers_all_mutable_approval_inputs(client, payment, change):
    case = reviewed_case(client, payment)
    with Session.begin() as session:
        p = session.get(Payment, payment['id'])
        prop = session.get(Proposal, case['proposal']['id'])
        if change == 'policy': prop.policy_hash = 'old'
        if change == 'evidence': prop.evidence_sha256 = 'old-image'
        if change == 'balance': p.refunded_cents = 1999
        if change == 'window': p.captured_at = time.time()-31*86400
        if change == 'fingerprint': prop.fingerprint = 'modified'
    prop = client.get(f"/api/cases/{case['id']}/packet").json()['proposals'][0]
    assert prop['state'] == 'stale' and not prop['can_approve'] and prop['current_issues']


def test_replayed_case_creation_is_idempotent_and_payload_bound(client, payment):
    body = {'request_id':str(uuid4()),'payment_id':payment['id'],'statement':'A damaged desk item needs a refund.','requested_cents':500}
    first = client.post('/api/cases',json=body)
    second = client.post('/api/cases',json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()['id'] == second.json()['id'] == body['request_id']
    assert client.post('/api/cases',json={**body,'requested_cents':600}).status_code == 409
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Case)) == 1
        assert session.scalar(select(func.count()).select_from(Audit).where(Audit.action=='case_created')) == 1


def test_duplicate_analysis_is_rejected_before_model_and_quota(client, payment, monkeypatch):
    case = reviewed_case(client, payment)
    original = main.analyze
    started, release = Event(), Event()
    calls = []
    monkeypatch.setattr(settings,'gemini_api_key','fictional-test-key')
    # The mocked model returns preview without consulting a provider.
    async def mocked(c,p):
        saved = settings.gemini_api_key
        try:
            settings.gemini_api_key = ''
            return await original(c,p)
        finally: settings.gemini_api_key = saved
    async def slow_mock(c,p):
        calls.append(c.id); started.set()
        while not release.is_set(): await asyncio.sleep(.01)
        return await mocked(c,p)
    monkeypatch.setattr(main,'analyze',slow_mock)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(client.post, f"/api/cases/{case['id']}/analyze")
        try:
            assert started.wait(3)
            current = next(c for c in client.get('/api/dashboard').json()['cases'] if c['id']==case['id'])
            assert current['analysis_in_progress']
            assert client.post(f"/api/cases/{case['id']}/analyze").status_code == 409
            with Session() as session:
                assert session.scalar(select(func.sum(Quota.used)).where(Quota.key.like('ai:%'))) == 1
        finally: release.set()
        assert first.result(timeout=5).status_code == 200
    assert calls == [case['id']]
    assert not next(c for c in client.get('/api/dashboard').json()['cases'] if c['id']==case['id'])['analysis_in_progress']


def test_analysis_failure_releases_lease_and_allows_retry(client, payment, monkeypatch):
    case = reviewed_case(client, payment)
    original = main.analyze
    async def fail(c,p): raise AIUnavailable('Provider temporarily unavailable.')
    monkeypatch.setattr(main,'analyze',fail)
    assert client.post(f"/api/cases/{case['id']}/analyze").status_code == 503
    with Session() as session:
        assert session.get(AnalysisLease,case['id']).token is None
    monkeypatch.setattr(main,'analyze',original)
    assert client.post(f"/api/cases/{case['id']}/analyze").status_code == 200


def test_expired_lease_can_be_recovered_and_old_owner_cannot_commit(client, payment, monkeypatch):
    case = reviewed_case(client, payment)
    with Session.begin() as session:
        lease=session.get(AnalysisLease,case['id']);lease.token='crashed-owner';lease.expires_at=time.time()-1
    assert client.post(f"/api/cases/{case['id']}/analyze").status_code == 200
    original = main.analyze
    async def replaced(c,p):
        with Session.begin() as session:
            lease=session.get(AnalysisLease,c.id);lease.token='new-owner';lease.expires_at=time.time()+90
        return await original(c,p)
    monkeypatch.setattr(main,'analyze',replaced)
    with Session() as session: before=session.scalar(select(func.count()).select_from(Proposal))
    assert client.post(f"/api/cases/{case['id']}/analyze").status_code == 409
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Proposal)) == before
        assert session.get(AnalysisLease,case['id']).token == 'new-owner'
