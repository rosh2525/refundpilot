import asyncio
import logging
import time
from sqlalchemy import and_, or_, select, update
from .config import settings
from .db import Session, Job, Refund, Payment, Webhook, audit, uid
from .paypal import paypal, PayPalError, cents

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "cancelled"}


def claim_job():
    now = time.time()
    eligible = or_(and_(Job.state == "pending", Job.run_after <= now), and_(Job.state == "running", Job.lease_until < now))
    with Session.begin() as session:
        job = session.scalar(select(Job).where(eligible).order_by(Job.run_after).with_for_update(skip_locked=True).limit(1))
        if not job:
            return None
        token = uid()
        changed = session.execute(update(Job).where(Job.id == job.id, eligible).values(state="running", lease_until=now + 120, lease_token=token, attempts=Job.attempts + 1))
        if not changed.rowcount:
            return None
        return job.id, job.kind, job.reference_id, token


def finish_job(job_id, token, retry_in=None):
    with Session.begin() as session:
        session.execute(update(Job).where(Job.id == job_id, Job.lease_token == token).values(
            state="done" if retry_in is None else "pending", run_after=time.time() + (retry_in or 0), lease_until=0, lease_token=None))


def mark_unknown(refund_id, message):
    with Session.begin() as session:
        op = session.get(Refund, refund_id)
        if op and op.status not in TERMINAL:
            op.status = "unknown"
            op.last_error = message
            op.updated_at = time.time()


def settle(refund_id, state, result=None, message=None):
    with Session.begin() as session:
        op = session.scalar(select(Refund).where(Refund.id == refund_id).with_for_update())
        if not op or op.status in TERMINAL:
            return
        if result:
            remote_id = result.get("id")
            try:
                valid = bool(remote_id) and cents(result["amount"]) == op.amount_cents
            except (PayPalError, KeyError, TypeError):
                valid = False
            if not valid or (op.paypal_refund_id and op.paypal_refund_id != remote_id):
                op.status = "unknown"
                op.last_error = "PayPal refund identity or amount did not match the approved operation. Manual reconciliation required."
                return
            op.paypal_refund_id = remote_id
        op.updated_at = time.time()
        if state not in TERMINAL:
            op.status = "pending" if state == "pending" else "unknown"
            op.last_error = message
            return
        # Atomic reservation claim also protects SQLite and late/duplicate workers.
        released = session.execute(update(Refund).where(Refund.id == refund_id, Refund.reservation_active.is_(True)).values(reservation_active=False, status=state, last_error=message))
        if released.rowcount:
            completed = op.amount_cents if state == "completed" else 0
            session.execute(update(Payment).where(Payment.id == op.payment_id).values(
                reserved_cents=Payment.reserved_cents - op.amount_cents,
                refunded_cents=Payment.refunded_cents + completed, version=Payment.version + 1))
            session.flush()
            payment = session.get(Payment, op.payment_id, populate_existing=True)
            if state == "completed":
                payment.status = "REFUNDED" if payment.refunded_cents == payment.amount_cents else "PARTIALLY_REFUNDED"
            audit(session, "refund_" + state, operation_id=op.id, amount_cents=op.amount_cents, provider_refund_id=op.paypal_refund_id)


async def process_refund(refund_id):
    with Session() as session:
        op = session.get(Refund, refund_id)
        if not op or op.status in TERMINAL:
            return None
        payment = session.get(Payment, op.payment_id)
        capture_id, source = payment.capture_id, payment.source
        amount, request_id, payload = op.amount_cents, op.request_id, op.payload
        remote_id, attempts, created = op.paypal_refund_id, op.attempts, op.created_at
    if source == "fixture":
        if settings.mode != "preview":
            mark_unknown(refund_id, "Preview transactions cannot execute in sandbox mode.")
            return None
        settle(refund_id, "completed", {"id": "PREVIEW-" + refund_id, "status": "COMPLETED", "amount": {"value": f"{amount / 100:.2f}", "currency_code": "USD"}})
        return None
    if settings.mode != "sandbox":
        mark_unknown(refund_id, "Sandbox transaction is unavailable while the server is in preview mode.")
        return None
    if not remote_id and time.time() - created > 44 * 86400:
        mark_unknown(refund_id, "Automatic recovery stopped before the provider idempotency window expires. Reconcile manually; do not create a new refund.")
        return None
    if not remote_id and attempts >= 5:
        mark_unknown(refund_id, "The outcome is still uncertain after five attempts. Check the PayPal sandbox dashboard; the amount remains reserved.")
        return None
    try:
        if remote_id:
            result = await paypal.get_refund(remote_id)
        else:
            if attempts == 0:
                capture = await paypal.get_capture(capture_id)
                if cents(capture["amount"]) != payment.amount_cents or capture.get("id") != capture_id or capture.get("status") not in {"COMPLETED", "PARTIALLY_REFUNDED"}:
                    settle(refund_id, "failed", message="The original capture changed or is not refundable. Review the payment before creating another request.")
                    return None
                if capture["status"] == "PARTIALLY_REFUNDED" and payment.refunded_cents == 0:
                    settle(refund_id, "failed", message="An untracked refund was detected. This app only manages its own recorded refunds.")
                    return None
            with Session.begin() as session:
                session.execute(update(Refund).where(Refund.id == refund_id, Refund.status.not_in(TERMINAL)).values(status="executing", attempts=Refund.attempts + 1, updated_at=time.time()))
            result = await paypal.refund(capture_id, payload, request_id)
        state = str(result.get("status", "UNKNOWN")).lower()
        settle(refund_id, state, result)
        with Session() as session:
            latest = session.get(Refund, refund_id)
            return None if latest.status in TERMINAL else 60
    except PayPalError as exc:
        if exc.uncertain or remote_id or attempts > 0:
            mark_unknown(refund_id, str(exc))
            return min(300, 15 * (attempts + 1))
        settle(refund_id, "failed", message=str(exc))
        return None
    except (KeyError, TypeError, ValueError):
        mark_unknown(refund_id, "PayPal returned an unexpected representation. The refund remains reserved for reconciliation.")
        return 60


async def process_capture(payment_id):
    with Session() as session:
        payment = session.get(Payment, payment_id)
        if not payment or payment.source != "paypal_sandbox" or not payment.capture_id or settings.mode != "sandbox":
            return None
        capture_id = payment.capture_id
    value = await paypal.get_capture(capture_id)
    if value.get("id") != capture_id or cents(value["amount"]) != payment.amount_cents:
        return None
    state = value.get("status", "UNKNOWN")
    with Session.begin() as session:
        current = session.get(Payment, payment_id)
        if current.status != state:
            current.status = state
            current.version += 1
            audit(session, "capture_reconciled", payment_id=payment_id, provider_status=state)
    return 60 if state == "PENDING" else None


async def process_webhook(event_id):
    with Session.begin() as session:
        event = session.get(Webhook, event_id)
        if not event or event.processed:
            return
        # A webhook is a reconciliation signal, never a command to issue a refund.
        jobs = session.scalars(select(Job).join(Refund, Job.reference_id == Refund.id).where(Refund.status.not_in(TERMINAL))).all()
        for job in jobs:
            if job.state != "running":
                job.state, job.run_after = "pending", time.time()
        resource = event.payload.get("resource", {})
        capture_id = resource.get("id") if event.event_type.startswith("PAYMENT.CAPTURE.") else None
        if capture_id:
            payment = session.scalar(select(Payment).where(Payment.capture_id == capture_id, Payment.source == "paypal_sandbox"))
            if payment:
                reference = "capture:" + payment.id
                capture_job = session.scalar(select(Job).where(Job.reference_id == reference))
                if not capture_job:
                    session.add(Job(kind="capture", reference_id=reference))
                elif capture_job.state != "running":
                    capture_job.state, capture_job.run_after = "pending", time.time()
        event.processed = True
        audit(session, "verified_webhook_received", environment="sandbox", event_id=event.event_id, event_type=event.event_type)


async def run_once():
    claim = claim_job()
    if not claim:
        return False
    job_id, kind, reference_id, token = claim
    try:
        if kind == "refund":
            delay = await process_refund(reference_id)
        elif kind == "capture":
            delay = await process_capture(reference_id.removeprefix("capture:"))
        else:
            await process_webhook(reference_id)
            delay = None
        finish_job(job_id, token, delay)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Job processing failed; durable lease will be retried")
        finish_job(job_id, token, 60)
    return True


async def worker_loop():
    while True:
        try:
            active = await run_once()
            await asyncio.sleep(0.2 if active else 2)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Worker recovered from an unexpected error")
            await asyncio.sleep(3)
