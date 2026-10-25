"""Shared approval transaction used by the merchant API and isolated safety lab.

The caller owns the transaction. This module only persists a reservation/job;
it never calls a payment provider.
"""
import hmac
from fastapi import HTTPException
from sqlalchemy import select, update
from .config import POLICY, POLICY_HASH
from .db import Case, Evidence, Payment, Proposal, Refund, Job, audit, as_dict
from .policy import blockers, fingerprint


def approve_proposal(session, proposal_id, *, confirmed, reviewed_fingerprint, mode):
    proposal = session.get(Proposal, proposal_id)
    if not proposal:
        raise HTTPException(404, "Proposal not found.")
    case = session.get(Case, proposal.case_id)
    payment = session.scalar(select(Payment).where(Payment.id == case.payment_id, Payment.source == ("fixture" if mode == "preview" else "paypal_sandbox")))
    if not payment:
        raise HTTPException(404, "Payment not found for this merchant and environment.")
    if not confirmed or not reviewed_fingerprint.isascii() or not hmac.compare_digest(reviewed_fingerprint, proposal.fingerprint):
        raise HTTPException(400, "Confirm the exact reviewed proposal before approval.")
    existing = session.scalar(select(Refund).where(Refund.proposal_id == proposal_id))
    if existing:
        return as_dict(existing)
    if proposal.state != "ready" or proposal.blockers or proposal.policy_hash != POLICY_HASH or proposal.decision not in {"refund", "preview"}:
        raise HTTPException(409, "The proposal is blocked, outdated, or already superseded.")
    if proposal.decision == "preview" and mode != "preview":
        raise HTTPException(409, "Preview proposals cannot execute PayPal refunds.")
    evidence = session.scalar(select(Evidence).where(Evidence.case_id == case.id))
    current_evidence_hash = evidence.sha256 if evidence else None
    if proposal.evidence_sha256 != current_evidence_hash:
        raise HTTPException(409, "The attached evidence changed; analyze it again.")
    if fingerprint(case.id, payment.capture_id, proposal.amount_cents, proposal.payment_version, evidence_sha256=proposal.evidence_sha256) != proposal.fingerprint:
        raise HTTPException(409, "The approved proposal was modified; analyze it again.")
    errors = blockers(payment, case.requested_cents, proposal.amount_cents)
    if errors:
        raise HTTPException(409, " ".join(errors))
    # Atomic compare-and-reserve prevents two tabs/proposals from spending the same balance.
    reserved = session.execute(update(Payment).where(Payment.id == payment.id, Payment.version == proposal.payment_version,
        Payment.reserved_cents == 0, Payment.amount_cents - Payment.refunded_cents - Payment.reserved_cents >= proposal.amount_cents).values(
        reserved_cents=Payment.reserved_cents + proposal.amount_cents, version=Payment.version + 1))
    if not reserved.rowcount:
        raise HTTPException(409, "Payment state changed. Refresh and analyze a new proposal.")
    claimed = session.execute(update(Proposal).where(Proposal.id == proposal.id, Proposal.state == "ready").values(state="approved"))
    if not claimed.rowcount:
        raise HTTPException(409, "This proposal has already been handled.")
    operation = Refund(proposal_id=proposal.id, payment_id=payment.id, amount_cents=proposal.amount_cents,
        payload={"amount": {"value": f"{proposal.amount_cents // 100}.{proposal.amount_cents % 100:02d}", "currency_code": "USD"}, "note_to_payer": "Merchant-approved refund via RefundPilot"})
    session.add(operation)
    session.flush()
    session.add(Job(kind="refund", reference_id=operation.id))
    case.status = "approved"
    audit(session, "merchant_approved_refund", case.id, operation_id=operation.id, proposal_fingerprint=proposal.fingerprint, amount_cents=proposal.amount_cents, policy_version=POLICY["version"])
    return as_dict(operation)
