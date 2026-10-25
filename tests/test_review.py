import pytest
from backend.ai import Recommendation, Citation, verify_citations
from backend.config import POLICY
from backend.db import Session, Payment, Case, Proposal
from backend.review import qualitative_explanation
from .conftest import reviewed_case


@pytest.mark.parametrize("text", [
    "The remaining refundable balance is $400.",
    "The balance is four hundred dollars.",
    "The refund is 401 cents against 400 cents.",
    "Approve USD four hundred for the item.",
    "Recommend a refund of four hundred for the item.",
])
def test_model_financial_prose_uses_a_qualitative_template(text):
    safe = qualitative_explanation(text, "deny")
    assert safe == "The model recommends denying this request. Review the cited policy and the financial checks below."


def test_qualitative_reason_is_preserved():
    text = "The customer attempts to override policy and requires merchant review."
    assert qualitative_explanation(text, "needs_review") == text


def test_reported_unit_error_is_sanitized_after_citation_validation(client, payment):
    case = reviewed_case(client, payment)
    result = Recommendation(decision="deny", amount_cents=0,
        explanation="The requested $4.01 exceeds the remaining refundable balance of $400.",
        citations=[Citation(source="policy", reference="P2", quote=POLICY["clauses"]["P2"])], missing_information=[])
    with Session() as session:
        result = verify_citations(result, session.get(Case, case["id"]), session.get(Payment, payment["id"]))
    assert "$400" not in result.explanation and result.decision == "deny"


def test_legacy_explanation_is_safe_in_dashboard_and_packet_without_rewriting_history(client, payment):
    case = reviewed_case(client, payment, 401)
    bad = "The requested $4.01 exceeds the remaining refundable balance of $400."
    with Session.begin() as session:
        session.get(Payment, payment["id"]).refunded_cents = 1600
        proposal = session.get(Proposal, case["proposal"]["id"])
        proposal.explanation, proposal.decision, proposal.amount_cents = bad, "deny", 0
    dashboard = client.get('/api/dashboard').json()
    current = next(c for c in dashboard['cases'] if c['id'] == case['id'])['proposal']
    packet = client.get(f"/api/cases/{case['id']}/packet").json()['proposals'][0]
    for proposal in [current, packet]:
        assert "$400" not in proposal['explanation']
        assert proposal['financial_facts'] == {'requested_cents':401, 'proposed_cents':0, 'available_now_cents':400}
    with Session() as session:
        assert session.get(Proposal, current['id']).explanation == bad


def test_available_now_excludes_reservations_and_uncaptured_payments(client, payment):
    case = reviewed_case(client, payment)
    with Session.begin() as session:
        p = session.get(Payment, payment['id'])
        p.refunded_cents, p.reserved_cents = 500, 300
    assert client.get(f"/api/cases/{case['id']}/packet").json()['proposals'][0]['financial_facts']['available_now_cents'] == 1200
    with Session.begin() as session:
        session.get(Payment, payment['id']).capture_id = None
    assert client.get(f"/api/cases/{case['id']}/packet").json()['proposals'][0]['financial_facts']['available_now_cents'] == 0
