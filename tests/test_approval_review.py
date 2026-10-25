"""Approval retry integrity and evidence binding at the shared execution boundary."""
from dataclasses import asdict
import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.approval import approve_proposal
from backend.config import settings
from backend.db import Audit, Case, Evidence, Job, Payment, Proposal, Quota, Refund, Session
from backend.lab import run_scenario
from backend.policy import fingerprint
from .conftest import approved_refund, reviewed_case


def counts_and_reservation(payment_id):
    with Session() as session:
        return ([session.scalar(select(func.count()).select_from(model)) for model in (Refund, Job, Audit)],
                session.get(Payment, payment_id).reserved_cents)


@pytest.mark.parametrize("confirmed,fingerprint_value", [(False, None), (True, "tampered"), (False, "tampered")])
def test_completed_approval_retry_still_requires_exact_confirmation(client, payment, confirmed, fingerprint_value):
    operation, case = approved_refund(client, payment)
    proposal = case["proposal"]
    before = counts_and_reservation(payment["id"])
    response = client.post(f"/api/proposals/{proposal['id']}/approve", json={"confirmed": confirmed,
        "fingerprint": proposal["fingerprint"] if fingerprint_value is None else fingerprint_value})
    assert response.status_code == 400
    assert counts_and_reservation(payment["id"]) == before
    valid = client.post(f"/api/proposals/{proposal['id']}/approve", json={"confirmed": True, "fingerprint": proposal["fingerprint"]})
    assert valid.json()["id"] == operation["id"]


def attach_evidence(session, case_id, sha="a" * 64):
    session.add(Evidence(case_id=case_id, image_bytes=b"synthetic test bytes; not a provider input",
        mime_type="image/png", sha256=sha, size_bytes=49))


def test_adding_evidence_after_analysis_rejects_even_a_ready_proposal(client, payment):
    case = reviewed_case(client, payment)
    proposal = case["proposal"]
    with Session.begin() as session:
        attach_evidence(session, case["id"])
    before = counts_and_reservation(payment["id"])
    response = client.post(f"/api/proposals/{proposal['id']}/approve", json={"confirmed": True, "fingerprint": proposal["fingerprint"]})
    assert response.status_code == 409
    assert "evidence changed" in response.json()["detail"]
    assert counts_and_reservation(payment["id"]) == before


@pytest.mark.parametrize("mutation", ["changed_image", "removed_image", "missing_fingerprint_binding"])
def test_image_replacement_removal_and_unbound_fingerprint_cannot_execute(client, payment, mutation):
    case = reviewed_case(client, payment)
    proposal_id = case["proposal"]["id"]
    evidence_sha = "a" * 64
    with Session.begin() as session:
        attach_evidence(session, case["id"], evidence_sha)
        proposal = session.get(Proposal, proposal_id)
        proposal.evidence_sha256 = evidence_sha
        if mutation != "missing_fingerprint_binding":
            proposal.fingerprint = fingerprint(case["id"], payment["capture_id"], proposal.amount_cents,
                proposal.payment_version, evidence_sha256=evidence_sha)
        exact_fingerprint = proposal.fingerprint
    with Session.begin() as session:
        evidence = session.scalar(select(Evidence).where(Evidence.case_id == case["id"]))
        if mutation == "changed_image":
            evidence.sha256 = "b" * 64
        elif mutation == "removed_image":
            session.delete(evidence)
    before = counts_and_reservation(payment["id"])
    with pytest.raises(HTTPException) as error, Session.begin() as session:
        approve_proposal(session, proposal_id, confirmed=True, reviewed_fingerprint=exact_fingerprint, mode="preview")
    assert error.value.status_code == 409
    assert counts_and_reservation(payment["id"]) == before


def test_tampering_with_proposed_amount_invalidates_fingerprint(client, payment):
    proposal = reviewed_case(client, payment)["proposal"]
    with Session.begin() as session:
        session.get(Proposal, proposal["id"]).amount_cents = 600
    before = counts_and_reservation(payment["id"])
    response = client.post(f"/api/proposals/{proposal['id']}/approve", json={"confirmed": True, "fingerprint": proposal["fingerprint"]})
    assert response.status_code == 409
    assert "modified" in response.json()["detail"]
    assert counts_and_reservation(payment["id"]) == before


@pytest.mark.parametrize("scenario", ["duplicate_approval", "competing_approvals", "stale_policy", "prompt_injection"])
def test_lab_has_no_provider_worker_model_quota_or_configuration_side_effects(client, monkeypatch, scenario):
    from backend import ai, worker
    from backend.paypal import paypal
    def forbidden(*args, **kwargs):
        raise AssertionError("The isolated lab must not call external providers or execute workers.")
    monkeypatch.setattr(ai, "analyze", forbidden)
    monkeypatch.setattr(worker, "run_once", forbidden)
    for name in ("create_order", "capture", "refund", "get_refund", "verify"):
        if hasattr(paypal, name):
            monkeypatch.setattr(paypal, name, forbidden)
    before_settings = hashlib.sha256(repr(asdict(settings)).encode()).hexdigest()
    with Session() as session:
        before = {model.__tablename__: [tuple(row) for row in session.execute(select(model.__table__)).all()]
            for model in (Payment, Case, Proposal, Evidence, Refund, Job, Audit, Quota)}
    result = run_scenario(scenario)
    assert result["passed"], result
    assert hashlib.sha256(repr(asdict(settings)).encode()).hexdigest() == before_settings
    with Session() as session:
        after = {model.__tablename__: [tuple(row) for row in session.execute(select(model.__table__)).all()]
            for model in (Payment, Case, Proposal, Evidence, Refund, Job, Audit, Quota)}
    assert after == before
