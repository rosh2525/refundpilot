import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, delete
from backend.main import app
from backend.config import settings, POLICY_HASH
from backend.db import Session, Payment, Refund, Job, Proposal
from backend.worker import run_once, claim_job, finish_job
from .conftest import reviewed_case, approved_refund


def test_authenticated_access_required():
    with TestClient(app) as anon:
        assert anon.get("/api/dashboard").status_code == 401
        assert anon.get("/api/config").json()["authenticated"] is False


def test_csrf_and_origin_are_checked(client, payment):
    body = {"payment_id": payment["id"], "statement": "Please refund my damaged order.", "requested_cents": 500}
    assert client.post("/api/cases", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/cases", json=body, headers={"Origin": "https://untrusted.example"}).status_code == 403


def test_bad_password_rate_limit():
    with TestClient(app) as anon:
        for _ in range(10):
            assert anon.post("/api/session", json={"password": "wrong"}).status_code == 401
        assert anon.post("/api/session", json={"password": "wrong"}).status_code == 429


def test_preview_is_explicitly_labelled(client, payment):
    config = client.get("/api/config").json()
    assert config["mode"] == "preview" and not config["paypal_connected"] and not config["ai_connected"]
    case = reviewed_case(client, payment)
    assert case["proposal"]["source"] == "rule_based_preview"
    assert case["proposal"]["decision"] == "preview"
    assert "not connected" in case["proposal"]["explanation"]


@pytest.mark.parametrize("amount", [0, -1, 1.5, True, "500", 1000001])
def test_amount_requires_bounded_integer_cents(client, payment, amount):
    result = client.post("/api/cases", json={"payment_id": payment["id"], "statement": "Please refund this damaged item.", "requested_cents": amount})
    assert result.status_code == 422


def test_over_refund_and_old_payment_are_blocked(client, payment):
    case = reviewed_case(client, payment, 2500)
    assert case["proposal"]["state"] == "blocked"
    old = next(p for p in client.get("/api/dashboard").json()["payments"] if p["capture_id"] == "PREVIEW-CAPTURE-002")
    assert "30-day" in " ".join(reviewed_case(client, old)["proposal"]["blockers"])


def test_wrong_currency_is_blocked(client, payment):
    with Session.begin() as session:
        session.get(Payment, payment["id"]).currency = "EUR"
    assert "Only USD" in " ".join(reviewed_case(client, payment)["proposal"]["blockers"])


def test_unconfirmed_and_modified_fingerprint_cannot_approve(client, payment):
    proposal = reviewed_case(client, payment)["proposal"]
    path = f"/api/proposals/{proposal['id']}/approve"
    assert client.post(path, json={"confirmed": False, "fingerprint": proposal["fingerprint"]}).status_code == 400
    assert client.post(path, json={"confirmed": True, "fingerprint": "tampered"}).status_code == 400
    assert client.post(path, json={"confirmed": True, "fingerprint": proposal["fingerprint"], "amount_cents": 999999}).status_code == 422


def test_approval_retry_is_idempotent(client, payment):
    operation, case = approved_refund(client, payment)
    again = client.post(f"/api/proposals/{case['proposal']['id']}/approve", json={"confirmed": True, "fingerprint": case["proposal"]["fingerprint"]})
    assert again.json()["id"] == operation["id"]
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Refund)) == 1
        assert session.get(Payment, payment["id"]).reserved_cents == 500


def test_competing_proposals_cannot_both_reserve(client, payment):
    first = reviewed_case(client, payment, 1500)["proposal"]
    second = reviewed_case(client, payment, 1500)["proposal"]
    results = []
    for proposal in (first, second):
        results.append(client.post(f"/api/proposals/{proposal['id']}/approve", json={"confirmed": True, "fingerprint": proposal["fingerprint"]}).status_code)
    assert results == [200, 409]
    with Session() as session:
        assert session.get(Payment, payment["id"]).reserved_cents == 1500


def test_simultaneous_approvals_reserve_once(client, payment):
    proposals = [reviewed_case(client, payment, 1500)["proposal"] for _ in range(2)]
    def approve(proposal):
        return client.post(f"/api/proposals/{proposal['id']}/approve", json={"confirmed": True, "fingerprint": proposal["fingerprint"]}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(approve, proposals))
    assert sorted(statuses) == [200, 409]
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Refund)) == 1


def test_state_or_policy_change_invalidates_approval(client, payment):
    proposal = reviewed_case(client, payment)["proposal"]
    with Session.begin() as session:
        session.get(Payment, payment["id"]).version += 1
    assert client.post(f"/api/proposals/{proposal['id']}/approve", json={"confirmed": True, "fingerprint": proposal["fingerprint"]}).status_code == 409
    with Session.begin() as session:
        session.get(Proposal, proposal["id"]).policy_hash = "changed"
    assert client.post(f"/api/proposals/{proposal['id']}/approve", json={"confirmed": True, "fingerprint": proposal["fingerprint"]}).status_code == 409


def test_superseded_analysis_cannot_execute(client, payment):
    case = reviewed_case(client, payment)
    old = case["proposal"]
    assert client.post(f"/api/cases/{case['id']}/analyze").status_code == 200
    assert client.post(f"/api/proposals/{old['id']}/approve", json={"confirmed": True, "fingerprint": old["fingerprint"]}).status_code == 409


@pytest.mark.asyncio
async def test_preview_refund_settles_once(client, payment):
    operation, _ = approved_refund(client, payment)
    assert await run_once()
    assert not await run_once()
    with Session() as session:
        current = session.get(Payment, payment["id"])
        assert current.refunded_cents == 500 and current.reserved_cents == 0
        op = session.get(Refund, operation["id"])
        assert op.status == "completed" and op.paypal_refund_id.startswith("PREVIEW-")


@pytest.mark.asyncio
async def test_expired_job_lease_recovers_after_restart(client, payment):
    operation, _ = approved_refund(client, payment)
    first = claim_job()
    assert first is not None and claim_job() is None
    with Session.begin() as session:
        session.get(Job, first[0]).lease_until = time.time() - 1
    recovered = claim_job()
    assert recovered[0] == first[0] and recovered[3] != first[3]
    finish_job(first[0], first[3])
    with Session() as session:
        assert session.get(Job, first[0]).state == "running"
    with Session.begin() as session:
        session.get(Job, first[0]).lease_until = time.time() - 1
    assert await run_once()
    with Session() as session:
        assert session.get(Refund, operation["id"]).status == "completed"


def test_webhook_simulations_do_not_bypass_signature_verification(client):
    response = client.post("/api/paypal/webhook", json={"id": "fake", "event_type": "PAYMENT.CAPTURE.REFUNDED"})
    assert response.status_code == 409


def test_unknown_capture_cannot_be_injected(client):
    result = client.post("/api/cases", json={"payment_id": "foreign-payment", "statement": "Please refund this other merchant's order.", "requested_cents": 500})
    assert result.status_code == 404


@pytest.mark.asyncio
async def test_missing_reconciliation_job_is_restored_without_new_refund(client, payment):
    operation, _ = approved_refund(client, payment)
    with Session.begin() as session:
        session.execute(delete(Job).where(Job.reference_id == operation['id']))
    path = f"/api/refunds/{operation['id']}/reconcile"
    for _ in range(2):
        response = client.post(path)
        assert response.status_code == 200
        assert response.json()['request_id'] == operation['request_id']
        assert response.json()['payload'] == operation['payload']
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Job).where(Job.reference_id == operation['id'])) == 1
        assert session.scalar(select(func.count()).select_from(Refund)) == 1
        assert session.get(Payment, payment['id']).reserved_cents == operation['amount_cents']
    assert await run_once()
    assert not await run_once()
    with Session() as session:
        assert session.get(Refund, operation['id']).status == 'completed'
        assert session.get(Payment, payment['id']).refunded_cents == operation['amount_cents']


def test_reconcile_preserves_running_lease(client, payment):
    operation, _ = approved_refund(client, payment)
    claim = claim_job()
    with Session() as session:
        before = session.get(Job, claim[0]).lease_until
    assert client.post(f"/api/refunds/{operation['id']}/reconcile").status_code == 200
    with Session() as session:
        job = session.get(Job, claim[0])
        assert job.state == 'running' and job.lease_token == claim[3] and job.lease_until == before


def test_concurrent_reconciliation_restores_one_job(client, payment):
    operation, _ = approved_refund(client, payment)
    with Session.begin() as session:
        session.execute(delete(Job).where(Job.reference_id == operation['id']))
    def reconcile(_):
        return client.post(f"/api/refunds/{operation['id']}/reconcile").status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(reconcile, range(2))) == [200, 200]
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Job).where(Job.reference_id == operation['id'])) == 1
        assert session.get(Refund, operation['id']).request_id == operation['request_id']
        assert session.get(Payment, payment['id']).reserved_cents == operation['amount_cents']


@pytest.mark.asyncio
async def test_terminal_refund_does_not_recreate_missing_job(client, payment):
    operation, _ = approved_refund(client, payment)
    await run_once()
    with Session.begin() as session:
        session.execute(delete(Job).where(Job.reference_id == operation['id']))
    assert client.post(f"/api/refunds/{operation['id']}/reconcile").status_code == 200
    with Session() as session:
        assert session.scalar(select(Job).where(Job.reference_id == operation['id'])) is None
