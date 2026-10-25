"""Merchant-facing recommendations keep monetary facts separate from model prose."""
import re
from .db import as_dict

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


def proposal_view(proposal, case, payment):
    result = as_dict(proposal)
    result["explanation"] = qualitative_explanation(proposal.explanation, proposal.decision)
    refundable = payment.capture_id and payment.status in {"COMPLETED", "PARTIALLY_REFUNDED"}
    result["financial_facts"] = {
        "requested_cents": case.requested_cents,
        "proposed_cents": proposal.amount_cents,
        "available_now_cents": max(0, payment.amount_cents-payment.refunded_cents-payment.reserved_cents) if refundable else 0,
    }
    return result
