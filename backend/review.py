"""Merchant-facing recommendations keep monetary facts separate from model prose."""
import re
from .db import as_dict
from .config import POLICY_HASH
from .policy import blockers, fingerprint

_FINANCIAL_PROSE = re.compile(
    r"\d|[$€£¥₹]|\b(?:usd|dollars?|cents?|amounts?|balances?|zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundred|thousand|million|billion|half|quarter|twice)\b", re.IGNORECASE)
_DECISIONS = {
    "refund": "The model recommends a refund based on the cited evidence. Review the policy checks before approving.",
    "deny": "The model recommends denying this request. Review the cited policy and the financial checks below.",
    "needs_review": "The request needs further merchant review. Inspect the cited evidence and any missing or contradictory information.",
    "preview": "Rule-based simulation only. Review the fictional request and the policy checks; no AI assessment is claimed.",
}


def qualitative_explanation(text, decision):
    # Free-form numbers cannot be reliably matched to their intended financial
    # meaning. Preserve qualitative rationale, but use a template for numerical
    # or monetary assertions rather than guessing how to repair them.
    return _DECISIONS.get(decision, _DECISIONS["needs_review"]) if _FINANCIAL_PROSE.search(text) else text


def proposal_view(proposal, case, payment, *, has_refund=False, evidence_sha256=None):
    result = as_dict(proposal)
    result["explanation"] = qualitative_explanation(proposal.explanation, proposal.decision)
    refundable = payment.capture_id and payment.status in {"COMPLETED", "PARTIALLY_REFUNDED"}
    result["financial_facts"] = {
        "requested_cents": case.requested_cents,
        "proposed_cents": proposal.amount_cents,
        "available_now_cents": max(0, payment.amount_cents-payment.refunded_cents-payment.reserved_cents) if refundable else 0,
    }
    issues = []
    if proposal.state == "ready" and not has_refund:
        if proposal.payment_version != payment.version:
            issues.append("Payment state changed. Review the current balance and analyze again.")
        if proposal.policy_hash != POLICY_HASH:
            issues.append("Merchant policy changed. Analyze this request again.")
        if proposal.evidence_sha256 != evidence_sha256:
            issues.append("Photo evidence changed. Analyze this request again.")
        if proposal.fingerprint != fingerprint(case.id, payment.capture_id, proposal.amount_cents,
                proposal.payment_version, evidence_sha256=proposal.evidence_sha256):
            issues.append("Proposal details changed. Analyze this request again.")
        issues.extend(blockers(payment, case.requested_cents, proposal.amount_cents))
        if issues:
            result["state"] = "stale"
    result["current_issues"] = issues
    result["can_approve"] = result["state"] == "ready" and not has_refund and proposal.decision in {"refund", "preview"} and not proposal.blockers and not issues
    return result
