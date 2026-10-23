import time
import pytest
from sqlalchemy import select, func
from backend.config import settings
from backend.db import Session, Refund, Payment, Job, Webhook
from backend.paypal import paypal, PayPalError
from backend.worker import process_refund, settle, process_webhook, process_capture
from .conftest import approved_refund


def sandbox_operation(client, payment, monkeypatch):
    operation, case = approved_refund(client, payment)
    with Session.begin() as session:
        session.get(Payment, payment["id"]).source = "paypal_sandbox"
    monkeypatch.setattr(settings, "mode", "sandbox")
    return operation, case


async def capture_ok(capture_id):
    return {"id": capture_id, "status": "COMPLETED", "amount": {"value": "20.00", "currency_code": "USD"}}


def refund_result(status="COMPLETED", amount="5.00"):
    return {"id": "REFUND-TEST-123", "status": status, "amount": {"value": amount, "currency_code": "USD"}}


@pytest.mark.asyncio
async def test_lost_response_reuses_exact_payload_and_request_key(client, payment, monkeypatch):
    op, _ = sandbox_operation(client, payment, monkeypatch)
    monkeypatch.setattr(paypal, "get_capture", capture_ok)
    calls = []
    async def uncertain_then_ok(capture_id, payload, request_id):
        calls.append((capture_id, payload, request_id))
        if len(calls) == 1:
            raise PayPalError("lost response", uncertain=True)
        return refund_result()
    monkeypatch.setattr(paypal, "refund", uncertain_then_ok)
    assert await process_refund(op["id"]) is not None
    with Session() as session:
        assert session.get(Refund, op["id"]).status == "unknown"
        assert session.get(Payment, payment["id"]).reserved_cents == 500
    assert await process_refund(op["id"]) is None
    assert len(calls) == 2 and calls[0] == calls[1]
    with Session() as session:
        assert session.get(Payment, payment["id"]).refunded_cents == 500
    settle(op["id"], "completed", refund_result())
    with Session() as session:
        assert session.get(Payment, payment["id"]).refunded_cents == 500


@pytest.mark.asyncio
async def test_pending_refund_remains_reserved_until_provider_confirms(client, payment, monkeypatch):
    op, _ = sandbox_operation(client, payment, monkeypatch)
    monkeypatch.setattr(paypal, "get_capture", capture_ok)
    async def pending(*args): return refund_result("PENDING")
    async def completed(*args): return refund_result("COMPLETED")
    monkeypatch.setattr(paypal, "refund", pending)
    monkeypatch.setattr(paypal, "get_refund", completed)
    assert await process_refund(op["id"]) == 60
    with Session() as session:
        assert session.get(Refund, op["id"]).status == "pending"
        assert session.get(Payment, payment["id"]).refunded_cents == 0
        assert session.get(Payment, payment["id"]).reserved_cents == 500
    await process_refund(op["id"])
    with Session() as session:
        assert session.get(Refund, op["id"]).status == "completed"
        assert session.get(Payment, payment["id"]).reserved_cents == 0


@pytest.mark.asyncio
async def test_definite_rejection_releases_reservation(client, payment, monkeypatch):
    op, _ = sandbox_operation(client, payment, monkeypatch)
    monkeypatch.setattr(paypal, "get_capture", capture_ok)
    async def rejected(*args): raise PayPalError("REFUND_AMOUNT_EXCEEDED", code="REFUND_AMOUNT_EXCEEDED")
    monkeypatch.setattr(paypal, "refund", rejected)
    assert await process_refund(op["id"]) is None
    with Session() as session:
        assert session.get(Refund, op["id"]).status == "failed"
        assert session.get(Payment, payment["id"]).reserved_cents == 0


@pytest.mark.asyncio
async def test_retry_window_and_attempt_limit_fail_closed(client, payment, monkeypatch):
    op, _ = sandbox_operation(client, payment, monkeypatch)
    with Session.begin() as session:
        session.get(Refund, op["id"]).created_at = time.time() - 45 * 86400
    assert await process_refund(op["id"]) is None
    with Session() as session:
        assert session.get(Refund, op["id"]).status == "unknown"
        assert session.get(Payment, payment["id"]).reserved_cents == 500


@pytest.mark.asyncio
async def test_mismatched_provider_refund_amount_stays_unknown(client, payment, monkeypatch):
    op, _ = sandbox_operation(client, payment, monkeypatch)
    monkeypatch.setattr(paypal, "get_capture", capture_ok)
    async def mismatched(*args): return refund_result(amount="20.00")
    monkeypatch.setattr(paypal, "refund", mismatched)
    await process_refund(op["id"])
    with Session() as session:
        assert session.get(Refund, op["id"]).status == "unknown"
        assert session.get(Payment, payment["id"]).reserved_cents == 500


@pytest.mark.asyncio
async def test_completed_http_response_does_not_override_failed_status(client, payment, monkeypatch):
    op, _ = sandbox_operation(client, payment, monkeypatch)
    monkeypatch.setattr(paypal, "get_capture", capture_ok)
    async def failed(*args): return refund_result("FAILED")
    monkeypatch.setattr(paypal, "refund", failed)
    await process_refund(op["id"])
    with Session() as session:
        assert session.get(Refund, op["id"]).status == "failed"
        assert session.get(Payment, payment["id"]).refunded_cents == 0


@pytest.mark.asyncio
async def test_real_webhooks_require_valid_signature_and_are_deduplicated(client, monkeypatch):
    monkeypatch.setattr(settings, "mode", "sandbox")
    async def invalid(*args): return False
    async def valid(*args): return True
    event = {"id": "WH-VERIFIED-1", "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"id": "unknown"}}
    monkeypatch.setattr(paypal, "verify", invalid)
    assert client.post("/api/paypal/webhook", json=event).status_code == 400
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Webhook)) == 0
    monkeypatch.setattr(paypal, "verify", valid)
    assert client.post("/api/paypal/webhook", json=event).status_code == 200
    assert client.post("/api/paypal/webhook", json=event).status_code == 200
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Webhook)) == 1
    await process_webhook(event["id"])
    with Session() as session:
        assert session.get(Webhook, event["id"]).processed
        assert session.scalar(select(func.count()).select_from(Refund)) == 0


@pytest.mark.asyncio
async def test_pending_capture_reconciles_to_current_provider_state(client, payment, monkeypatch):
    with Session.begin() as session:
        current = session.get(Payment, payment["id"])
        current.source, current.status = "paypal_sandbox", "PENDING"
    monkeypatch.setattr(settings, "mode", "sandbox")
    monkeypatch.setattr(paypal, "get_capture", capture_ok)
    assert await process_capture(payment["id"]) is None
    with Session() as session:
        assert session.get(Payment, payment["id"]).status == "COMPLETED"


@pytest.mark.asyncio
async def test_paypal_signature_check_rejects_missing_or_foreign_headers():
    assert not await paypal.verify({}, {})
    headers = {name: "value" for name in ["paypal-transmission-id", "paypal-transmission-time", "paypal-cert-url", "paypal-transmission-sig", "paypal-auth-algo"]}
    headers["paypal-cert-url"] = "https://attacker.example/cert"
    assert not await paypal.verify(headers, {})


@pytest.mark.asyncio
async def test_signature_postback_preserves_original_event_bytes(monkeypatch):
    raw = b'{  "id" : "WH-RAW", "event_type":"PAYMENT.CAPTURE.COMPLETED" }'
    import json
    headers = {name: "value" for name in ["paypal-transmission-id", "paypal-transmission-time", "paypal-cert-url", "paypal-transmission-sig", "paypal-auth-algo"]}
    headers["paypal-cert-url"] = "https://api.sandbox.paypal.com/v1/notifications/certs/test"
    captured = []
    async def call(method, path, payload):
        captured.append(payload)
        return {"verification_status": "SUCCESS"}
    monkeypatch.setattr(paypal, "call", call)
    assert await paypal.verify(headers, json.loads(raw), raw)
    assert raw in captured[0]
    assert json.loads(captured[0])["webhook_event"]["id"] == "WH-RAW"
