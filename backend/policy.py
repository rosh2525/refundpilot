import hashlib
import json
import time
from .config import POLICY, POLICY_HASH

ALLOWED_CAPTURE_STATES = {"COMPLETED", "PARTIALLY_REFUNDED"}

def blockers(payment, requested_cents, amount_cents, now=None):
    now = time.time() if now is None else now
    errors = []
    if payment.currency != "USD":
        errors.append("Only USD is supported.")
    if not payment.capture_id or payment.status not in ALLOWED_CAPTURE_STATES:
        errors.append("The original payment is not a refundable captured payment.")
    if payment.captured_at is None or now - payment.captured_at > POLICY["window_days"] * 86400:
        errors.append("This payment is outside the merchant's 30-day refund window (P1).")
    if payment.captured_at is not None and payment.captured_at > now + 60:
        errors.append("Payment timestamp requires reconciliation.")
    if amount_cents <= 0:
        errors.append("The refund amount must be greater than zero.")
    if amount_cents > requested_cents:
        errors.append("The proposed amount exceeds the customer's requested amount (P2).")
    if amount_cents > payment.amount_cents - payment.refunded_cents - payment.reserved_cents:
        errors.append("The proposed amount exceeds the remaining refundable balance (P2).")
    if payment.reserved_cents:
        errors.append("An earlier refund is still reserved, pending, or unresolved.")
    return errors

def fingerprint(case_id, capture_id, amount_cents, payment_version, policy_hash=POLICY_HASH, evidence_sha256=None):
    value = [case_id, capture_id, amount_cents, payment_version, policy_hash]
    if evidence_sha256 is not None:
        value.append(evidence_sha256)
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()
