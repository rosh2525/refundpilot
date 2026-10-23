import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from .config import settings, POLICY, POLICY_HASH
from .db import Base, engine, Session, Payment, Case, Proposal, Refund, Job, Webhook, Audit, Quota, as_dict, audit, uid
from .policy import blockers, fingerprint
from .paypal import paypal, PayPalError, cents
from .ai import analyze, AIUnavailable
from .worker import worker_loop

logging.basicConfig(level=logging.INFO)
serializer = URLSafeTimedSerializer(settings.session_secret, salt="refundpilot-session-v1")
login_attempts = {}


def initialize():
    settings.validate()
    # Alembic manages production schema; create_all is only a local preview convenience.
    if settings.mode == "preview":
        Base.metadata.create_all(engine)
    with Session.begin() as session:
        if settings.mode == "preview" and not session.scalar(select(Payment.id).where(Payment.source == "fixture").limit(1)):
            session.add_all([
                Payment(order_id="PREVIEW-ORDER-001", capture_id="PREVIEW-CAPTURE-001", source="fixture", title="Everyday desk set", amount_cents=2000, status="COMPLETED", captured_at=time.time() - 2 * 86400),
                Payment(order_id="PREVIEW-ORDER-002", capture_id="PREVIEW-CAPTURE-002", source="fixture", title="Studio notebook bundle", amount_cents=4500, status="COMPLETED", captured_at=time.time() - 40 * 86400),
                Payment(order_id="PREVIEW-ORDER-003", capture_id="PREVIEW-CAPTURE-003", source="fixture", title="Minimal workspace kit", amount_cents=8000, refunded_cents=2000, status="PARTIALLY_REFUNDED", captured_at=time.time() - 5 * 86400),
            ])

@asynccontextmanager
async def lifespan(app):
    initialize()
    task = asyncio.create_task(worker_loop()) if settings.worker_enabled else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

app = FastAPI(title="RefundPilot", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

@app.middleware("http")
async def protection(request: Request, call_next):
    if request.headers.get("content-length", "").isdigit() and int(request.headers["content-length"]) > 65536:
        return JSONResponse({"detail": "Request is too large."}, status_code=413)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path != "/api/paypal/webhook":
        origin = request.headers.get("origin")
        if origin and origin != settings.app_url:
            return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
        if request.url.path != "/api/session":
            if not request.headers.get("x-csrf-token") or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), request.cookies.get("rp_csrf", "")):
                return JSONResponse({"detail": "Session verification failed. Refresh and sign in again."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def authenticated(request: Request):
    try:
        value = serializer.loads(request.cookies.get("rp_session", ""), max_age=12 * 3600)
        if value.get("role") != "merchant":
            raise BadSignature("invalid role")
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Sign in to the merchant demo.")

Auth = Annotated[None, Depends(authenticated)]

class LoginInput(BaseModel):
    password: str = Field(min_length=1, max_length=256)

class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payment_id: str = Field(min_length=1, max_length=36)
    statement: str = Field(min_length=15, max_length=6000)
    requested_cents: int = Field(gt=0, le=1000000, strict=True)

class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str
    confirmed: bool


def source_filter():
    return Payment.source == ("fixture" if settings.mode == "preview" else "paypal_sandbox")


def payment_or_404(session, payment_id):
    payment = session.scalar(select(Payment).where(Payment.id == payment_id, source_filter()))
    if not payment:
        raise HTTPException(404, "Payment not found for this merchant and environment.")
    return payment


def case_view(session, case):
    result = as_dict(case)
    proposal = session.scalar(select(Proposal).where(Proposal.case_id == case.id).order_by(Proposal.created_at.desc()).limit(1))
    result["proposal"] = as_dict(proposal) if proposal else None
    operation = session.scalar(select(Refund).join(Proposal).where(Proposal.case_id == case.id))
    result["refund"] = as_dict(operation) if operation else None
    return result

@app.exception_handler(PayPalError)
async def paypal_error(request, error):
    return JSONResponse({"detail": str(error)}, status_code=503)

@app.get("/health")
def health():
    try:
        with Session() as session:
            session.execute(select(1))
        return {"status": "ok", "mode": settings.mode}
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)

@app.get("/api/config")
def config(request: Request):
    logged_in = True
    try:
        authenticated(request)
    except HTTPException:
        logged_in = False
    return {"mode": settings.mode, "ai_connected": bool(settings.gemini_api_key), "model": settings.gemini_model if settings.gemini_api_key else None,
            "paypal_connected": settings.mode == "sandbox", "authenticated": logged_in, "policy": POLICY,
            "local_preview_password": "refundpilot-local" if settings.mode == "preview" and not settings.app_url.startswith("https://") and settings.app_password == "refundpilot-local" else None}

@app.post("/api/session")
def login(body: LoginInput, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    # Bound local limiter memory. Hosted service is a single process by design.
    for key in list(login_attempts):
        if now - login_attempts[key][0] > 600:
            login_attempts.pop(key, None)
    since, count = login_attempts.get(ip, (now, 0))
    if count >= 10:
        raise HTTPException(429, "Too many sign-in attempts. Try again in ten minutes.")
    if not hmac.compare_digest(hashlib.sha256(body.password.encode()).digest(), hashlib.sha256(settings.app_password.encode()).digest()):
        login_attempts[ip] = (since, count + 1)
        raise HTTPException(401, "The merchant password is incorrect.")
    login_attempts.pop(ip, None)
    secure = settings.app_url.startswith("https://")
    response.set_cookie("rp_session", serializer.dumps({"role": "merchant", "nonce": secrets.token_urlsafe(16)}), httponly=True, secure=secure, samesite="lax", max_age=43200)
    response.set_cookie("rp_csrf", secrets.token_urlsafe(24), secure=secure, samesite="lax", max_age=43200)
    return {"ok": True}

@app.delete("/api/session")
def logout(response: Response, _: Auth):
    response.delete_cookie("rp_session")
    response.delete_cookie("rp_csrf")
    return {"ok": True}

@app.get("/api/dashboard")
def dashboard(_: Auth):
    with Session() as session:
        payments = session.scalars(select(Payment).where(source_filter()).order_by(Payment.created_at.desc())).all()
        ids = [payment.id for payment in payments]
        cases = session.scalars(select(Case).where(Case.payment_id.in_(ids)).order_by(Case.created_at.desc())).all() if ids else []
        refunds = session.scalars(select(Refund).where(Refund.payment_id.in_(ids)).order_by(Refund.created_at.desc())).all() if ids else []
        events = session.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(40)).all()
        return {"payments": [as_dict(payment) for payment in payments], "cases": [case_view(session, case) for case in cases],
                "refunds": [as_dict(op) for op in refunds], "audit": [as_dict(event) for event in events]}

@app.post("/api/demo/orders")
async def create_order(_: Auth):
    with Session() as session:
        recent = session.scalar(select(func.count()).select_from(Payment).where(Payment.created_at > time.time() - 86400, source_filter()))
        if recent >= 100:
            raise HTTPException(429, "Daily demo purchase limit reached.")
    if settings.mode == "preview":
        payment = Payment(order_id="PREVIEW-ORDER-" + uid(), capture_id="PREVIEW-CAPTURE-" + uid(), source="fixture", amount_cents=2000, status="COMPLETED", captured_at=time.time())
    else:
        request_id = uid()
        value = await paypal.create_order(request_id)
        link = next((link["href"] for link in value.get("links", []) if link.get("rel") in {"approve", "payer-action"}), None)
        if not link or not value.get("id"):
            raise HTTPException(502, "PayPal did not return a buyer approval link.")
        from urllib.parse import urlsplit
        target = urlsplit(link)
        if target.scheme != "https" or target.hostname != "www.sandbox.paypal.com":
            raise HTTPException(502, "PayPal returned an unexpected approval destination.")
        payment = Payment(order_id=value["id"], source="paypal_sandbox", amount_cents=2000, status=value.get("status", "CREATED"), approval_url=link)
    with Session.begin() as session:
        session.add(payment)
        session.flush()
        audit(session, "demo_order_created", payment_id=payment.id, source=payment.source)
        result = as_dict(payment)
    return result

@app.post("/api/demo/orders/{payment_id}/capture")
async def capture_order(payment_id: str, _: Auth):
    with Session() as session:
        payment = payment_or_404(session, payment_id)
        if payment.capture_id:
            return as_dict(payment)
        order_id, request_id = payment.order_id, payment.capture_request_id
    value = await paypal.capture(order_id, request_id)
    try:
        capture = value["purchase_units"][0]["payments"]["captures"][0]
        if cents(capture["amount"]) != payment.amount_cents or value["id"] != order_id:
            raise ValueError()
        capture_id, state = capture["id"], capture["status"]
        timestamp = datetime.fromisoformat(capture["create_time"].replace("Z", "+00:00")).timestamp()
    except (KeyError, IndexError, ValueError):
        raise HTTPException(502, "PayPal capture could not be verified. Reconcile before attempting another payment.")
    with Session.begin() as session:
        current = payment_or_404(session, payment_id)
        if not current.capture_id:
            current.capture_id, current.status, current.captured_at = capture_id, state, timestamp
            current.version += 1
            audit(session, "payment_captured", payment_id=current.id, capture_id=capture_id)
            if state == "PENDING":
                session.add(Job(kind="capture", reference_id="capture:" + current.id))
        return as_dict(current)

@app.post("/api/cases", status_code=201)
def create_case(body: CaseInput, _: Auth):
    with Session.begin() as session:
        payment = payment_or_404(session, body.payment_id)
        if not payment.capture_id:
            raise HTTPException(409, "Complete buyer approval and payment capture first.")
        case = Case(payment_id=payment.id, statement=body.statement.strip(), requested_cents=body.requested_cents)
        if len(case.statement) < 15:
            raise HTTPException(422, "Provide a customer request of at least 15 characters.")
        session.add(case)
        session.flush()
        audit(session, "case_created", case.id, payment_id=payment.id, requested_cents=case.requested_cents)
        return case_view(session, case)

@app.post("/api/cases/{case_id}/analyze")
async def analyze_case(case_id: str, _: Auth):
    with Session.begin() as session:
        case = session.get(Case, case_id)
        if not case:
            raise HTTPException(404, "Case not found.")
        payment = payment_or_404(session, case.payment_id)
        if session.scalar(select(Refund.id).join(Proposal).where(Proposal.case_id == case_id)):
            raise HTTPException(409, "This case already has an approved refund operation.")
        if settings.gemini_api_key:
            day = datetime.now(timezone.utc).date().isoformat()
            key = "ai:" + day
            quota = session.get(Quota, key)
            if not quota:
                try:
                    with session.begin_nested():
                        session.add(Quota(key=key, used=0))
                        session.flush()
                except IntegrityError:
                    pass
            changed = session.execute(update(Quota).where(Quota.key == key, Quota.used < settings.ai_daily_limit).values(used=Quota.used + 1))
            if not changed.rowcount:
                raise HTTPException(429, "Daily AI request allowance reached. Please retry tomorrow.")
    try:
        recommendation, source = await analyze(case, payment)
    except AIUnavailable as exc:
        with Session.begin() as session:
            audit(session, "ai_unavailable", case_id, reason=str(exc))
        raise HTTPException(503, str(exc))
    checks = blockers(payment, case.requested_cents, recommendation.amount_cents)
    if recommendation.decision != "refund":
        checks.append("This recommendation requires review or denial; it is not executable.")
    if recommendation.missing_information:
        checks.extend(recommendation.missing_information)
    preview = source == "rule_based_preview" and settings.mode == "preview"
    if preview:
        # Deliberately separate simulated workflow from AI-backed proposals.
        checks = blockers(payment, case.requested_cents, recommendation.amount_cents)
    with Session.begin() as session:
        current = session.get(Case, case_id)
        if session.scalar(select(Refund.id).join(Proposal).where(Proposal.case_id == case_id)):
            raise HTTPException(409, "A refund was already approved while this analysis was running.")
        session.execute(update(Proposal).where(Proposal.case_id == case_id, Proposal.state == "ready").values(state="superseded"))
        proposal = Proposal(case_id=case_id, decision="preview" if preview else recommendation.decision, amount_cents=recommendation.amount_cents,
            explanation=recommendation.explanation, citations=[citation.model_dump() for citation in recommendation.citations], blockers=checks,
            source=source, policy_hash=POLICY_HASH, payment_version=payment.version,
            fingerprint=fingerprint(case_id, payment.capture_id, recommendation.amount_cents, payment.version), state="blocked" if checks else "ready")
        session.add(proposal)
        current.status = "reviewed"
        session.flush()
        audit(session, "recommendation_created", case_id, proposal_id=proposal.id, source=source, decision=proposal.decision)
        return case_view(session, current)

@app.post("/api/proposals/{proposal_id}/approve")
def approve(proposal_id: str, body: ApprovalInput, _: Auth):
    with Session.begin() as session:
        proposal = session.get(Proposal, proposal_id)
        if not proposal:
            raise HTTPException(404, "Proposal not found.")
        case = session.get(Case, proposal.case_id)
        payment = payment_or_404(session, case.payment_id)
        existing = session.scalar(select(Refund).where(Refund.proposal_id == proposal_id))
        if existing:
            return as_dict(existing)
        if not body.confirmed or not hmac.compare_digest(body.fingerprint, proposal.fingerprint):
            raise HTTPException(400, "Confirm the exact reviewed proposal before approval.")
        if proposal.state != "ready" or proposal.blockers or proposal.policy_hash != POLICY_HASH or proposal.decision not in {"refund", "preview"}:
            raise HTTPException(409, "The proposal is blocked, outdated, or already superseded.")
        if proposal.decision == "preview" and settings.mode != "preview":
            raise HTTPException(409, "Preview proposals cannot execute PayPal refunds.")
        if fingerprint(case.id, payment.capture_id, proposal.amount_cents, proposal.payment_version) != proposal.fingerprint:
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

@app.post("/api/refunds/{refund_id}/reconcile")
def reconcile(refund_id: str, _: Auth):
    with Session.begin() as session:
        operation = session.get(Refund, refund_id)
        if not operation:
            raise HTTPException(404, "Refund operation not found.")
        payment_or_404(session, operation.payment_id)
        if operation.status in {"completed", "failed", "cancelled"}:
            return as_dict(operation)
        job = session.scalar(select(Job).where(Job.reference_id == operation.id))
        if job.state != "running":
            job.state, job.run_after = "pending", time.time()
        audit(session, "reconciliation_requested", operation_id=operation.id)
        return as_dict(operation)

@app.post("/api/paypal/webhook")
async def webhook(request: Request):
    if settings.mode != "sandbox":
        raise HTTPException(409, "Real PayPal webhooks are only accepted in sandbox mode.")
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > 65536:
            raise HTTPException(413, "Webhook is too large.")
    try:
        value = json.loads(raw)
        event_id, event_type = value["id"], value["event_type"]
        if not isinstance(event_id, str) or not isinstance(event_type, str) or len(event_id) > 100 or len(event_type) > 100:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Malformed PayPal event.")
    if not await paypal.verify(dict(request.headers), value, raw):
        raise HTTPException(400, "PayPal webhook signature verification failed.")
    try:
        with Session.begin() as session:
            session.add(Webhook(event_id=event_id, event_type=event_type, payload=value))
            session.add(Job(kind="webhook", reference_id=event_id))
    except IntegrityError:
        pass
    return {"received": True}

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found.")
    if (DIST / "index.html").exists():
        return FileResponse(DIST / "index.html")
    return JSONResponse({"message": "Build the frontend with npm run build inside frontend/, or run the Vite development server."})
