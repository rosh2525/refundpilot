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
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from .config import settings, POLICY, POLICY_HASH
from .db import Base, engine, Session, Payment, Case, Evidence, Proposal, Refund, Job, Webhook, Audit, Quota, as_dict, audit, uid
from .policy import blockers, fingerprint
from .approval import approve_proposal
from .paypal import paypal, PayPalError, cents
from .ai import analyze, AIUnavailable
from .worker import worker_loop
from .evidence import normalize_image, EvidenceError, MAX_BASE64_LENGTH
from .lab import lab_config, run_scenario, Scenario

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
    image_upload = request.method == "POST" and request.url.path.startswith("/api/cases/") and request.url.path.endswith("/evidence")
    body_limit = MAX_BASE64_LENGTH + 4096 if image_upload else 65536
    if request.headers.get("content-length", "").isdigit() and int(request.headers["content-length"]) > body_limit:
        return JSONResponse({"detail": "Request is too large."}, status_code=413)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path != "/api/paypal/webhook":
        origin = request.headers.get("origin")
        if origin and origin != settings.app_url:
            return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
        if request.url.path != "/api/session":
            csrf_header, csrf_cookie = request.headers.get("x-csrf-token", ""), request.cookies.get("rp_csrf", "")
            if not csrf_header or not csrf_header.isascii() or not csrf_cookie.isascii() or not hmac.compare_digest(csrf_header, csrf_cookie):
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
    return_shipping_cents: int | None = Field(default=None, ge=0, le=1000000, strict=True)
    restocking_cents: int | None = Field(default=None, ge=0, le=1000000, strict=True)

class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_base64: str = Field(min_length=1, max_length=MAX_BASE64_LENGTH)
    media_type: str = Field(max_length=30)

class LabInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Scenario

class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(min_length=1, max_length=128)
    confirmed: bool = Field(strict=True)


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
    evidence = session.scalar(select(Evidence).where(Evidence.case_id == case.id))
    result["evidence"] = evidence_metadata(evidence) if evidence else None
    result["evidence_replacement_required"] = not evidence and evidence_was_removed(session, case.id)
    result["return_economics"] = return_economics(case)
    return result


def evidence_metadata(evidence):
    return {"id": evidence.id, "sha256": evidence.sha256, "mime_type": evidence.mime_type,
            "size_bytes": evidence.size_bytes, "url": f"/api/cases/{evidence.case_id}/evidence", "created_at": evidence.created_at}


def evidence_was_removed(session, case_id):
    return bool(session.scalar(select(Audit.id).where(Audit.case_id == case_id, Audit.action == "evidence_removed").limit(1)))


def prepare_evidence_change(session, case_id):
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found.")
    payment = payment_or_404(session, case.payment_id)
    # Serialize attachment changes with approvals on the same payment.
    changed = session.execute(update(Payment).where(Payment.id == payment.id, Payment.version == payment.version,
        Payment.reserved_cents == 0).values(version=Payment.version + 1))
    if not changed.rowcount:
        raise HTTPException(409, "Payment state changed or a refund is unresolved. Refresh before changing evidence.")
    if session.scalar(select(Refund.id).join(Proposal).where(Proposal.case_id == case_id)):
        raise HTTPException(409, "Evidence cannot change after this case has an approved refund.")
    session.execute(update(Proposal).where(Proposal.case_id == case_id,
        Proposal.state.in_(["ready", "blocked"])).values(state="superseded"))
    case.status = "new"
    return case


def return_economics(case):
    if case.return_shipping_cents is None or case.restocking_cents is None:
        return None
    handling = case.return_shipping_cents + case.restocking_cents
    return {"estimated_handling_cents": handling, "partial_refund_cents": case.requested_cents,
            "difference_cents": handling - case.requested_cents,
            "disclaimer": "Merchant-supplied handling estimate minus requested partial refund. Not net margin or full-return savings: excludes item recovery value, full refund, fees, tax, and replacement costs."}


def consume_quota(session, prefix, limit, message):
    key = prefix + ":" + datetime.now(timezone.utc).date().isoformat()
    if not session.get(Quota, key):
        try:
            with session.begin_nested():
                session.add(Quota(key=key, used=0)); session.flush()
        except IntegrityError:
            pass
    changed = session.execute(update(Quota).where(Quota.key == key, Quota.used < limit).values(used=Quota.used + 1))
    if not changed.rowcount:
        raise HTTPException(429, message)

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
        case = Case(payment_id=payment.id, statement=body.statement.strip(), requested_cents=body.requested_cents,
                    return_shipping_cents=body.return_shipping_cents, restocking_cents=body.restocking_cents)
        if len(case.statement) < 15:
            raise HTTPException(422, "Provide a customer request of at least 15 characters.")
        session.add(case)
        session.flush()
        audit(session, "case_created", case.id, payment_id=payment.id, requested_cents=case.requested_cents)
        return case_view(session, case)

@app.post("/api/cases/{case_id}/evidence", status_code=201)
async def attach_evidence(case_id: str, request: Request, _: Auth):
    # Bound streamed bodies too; Content-Length may be absent or incorrect.
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > MAX_BASE64_LENGTH + 4096:
            raise HTTPException(413, "The image must be at most 2 MiB.")
    try:
        body = EvidenceInput.model_validate_json(bytes(raw))
        normalized = normalize_image(body.image_base64, body.media_type)
    except ValidationError:
        raise HTTPException(422, "Provide a bounded base64 JPEG/PNG image and its media_type.")
    except EvidenceError as exc:
        raise HTTPException(422, str(exc))
    with Session.begin() as session:
        prepare_evidence_change(session, case_id)
        consume_quota(session, "images", 20, "Daily evidence upload allowance reached. Try again tomorrow.")
        image = session.scalar(select(Evidence).where(Evidence.case_id == case_id))
        previous_sha256 = image.sha256 if image else None
        total = session.scalar(select(func.coalesce(func.sum(Evidence.size_bytes), 0)))
        if total - (image.size_bytes if image else 0) + normalized.size_bytes > 20 * 1024 * 1024:
            raise HTTPException(413, "The demo's 20 MiB evidence storage allowance is full.")
        if image is None:
            image = Evidence(case_id=case_id)
            session.add(image)
        image.image_bytes, image.mime_type = normalized.image_bytes, normalized.mime_type
        image.sha256, image.size_bytes = normalized.sha256, normalized.size_bytes
        image.created_at = time.time()
        session.flush()
        audit(session, "evidence_attached", case_id, sha256=image.sha256, previous_sha256=previous_sha256, size_bytes=image.size_bytes)
        return evidence_metadata(image)


@app.delete("/api/cases/{case_id}/evidence")
def remove_evidence(case_id: str, _: Auth):
    with Session.begin() as session:
        case = prepare_evidence_change(session, case_id)
        image = session.scalar(select(Evidence).where(Evidence.case_id == case_id))
        if not image:
            raise HTTPException(404, "No evidence image attached.")
        audit(session, "evidence_removed", case_id, sha256=image.sha256, size_bytes=image.size_bytes,
              replacement_required=True)
        session.delete(image)
        session.flush()
        return case_view(session, case)


@app.get("/api/cases/{case_id}/evidence")
def get_evidence(case_id: str, _: Auth):
    with Session() as session:
        case = session.get(Case, case_id)
        if not case:
            raise HTTPException(404, "Case not found.")
        payment_or_404(session, case.payment_id)
        image = session.scalar(select(Evidence).where(Evidence.case_id == case_id))
        if not image:
            raise HTTPException(404, "No evidence image attached.")
        return Response(image.image_bytes, media_type=image.mime_type, headers={"Content-Disposition":"inline"})


@app.get("/api/cases/{case_id}/packet")
def review_packet(case_id: str, _: Auth):
    with Session() as session:
        case = session.get(Case, case_id)
        if not case:
            raise HTTPException(404, "Case not found.")
        payment = payment_or_404(session, case.payment_id)
        proposals = session.scalars(select(Proposal).where(Proposal.case_id == case_id).order_by(Proposal.created_at)).all()
        refunds = session.scalars(select(Refund).join(Proposal).where(Proposal.case_id == case_id)).all()
        operation_ids = {op.id for op in refunds}
        provider_ids = {op.paypal_refund_id for op in refunds if op.paypal_refund_id}
        events = [event for event in session.scalars(select(Audit).order_by(Audit.created_at)).all()
                  if event.case_id == case_id or event.details.get("operation_id") in operation_ids]
        webhooks = []
        for event in session.scalars(select(Webhook)).all():
            resource = event.payload.get("resource", {})
            if resource.get("id") in provider_ids:
                webhooks.append({"event_id":event.event_id,"event_type":event.event_type,"verified_at":event.verified_at})
        image = session.scalar(select(Evidence).where(Evidence.case_id == case_id))
        return {"format":"refundpilot-review-packet-v1", "generated_at":time.time(), "mode":settings.mode,
                "purpose":"Merchant review draft; not submitted to PayPal and not a determination of dispute eligibility.",
                "limitations":["Customer statements and photos are unverified claims.","Local audit records do not independently prove delivery, authenticity, or fulfillment.","No bank details, API credentials, session cookies, or image bytes are included."],
                "payment":{key:getattr(payment,key) for key in ("id","order_id","capture_id","currency","amount_cents","refunded_cents","reserved_cents","status","captured_at")},
                "case":as_dict(case), "current_policy":POLICY, "evidence":evidence_metadata(image) if image else None,
                "return_economics":return_economics(case), "proposals":[as_dict(p) for p in proposals],
                "refunds":[as_dict(op) for op in refunds], "audit":[as_dict(event) for event in events], "verified_refund_notifications":webhooks}


@app.get("/api/lab")
def safety_lab(_: Auth):
    return lab_config()


@app.post("/api/lab/run")
def safety_lab_run(body: LabInput, _: Auth):
    with Session.begin() as session:
        consume_quota(session, "lab", 30, "Daily safety demonstration allowance reached. Try again tomorrow.")
    return run_scenario(body.scenario)


@app.post("/api/cases/{case_id}/analyze")
async def analyze_case(case_id: str, _: Auth):
    with Session.begin() as session:
        case = session.get(Case, case_id)
        if not case:
            raise HTTPException(404, "Case not found.")
        payment = payment_or_404(session, case.payment_id)
        image = session.scalar(select(Evidence).where(Evidence.case_id == case_id))
        evidence_hash = image.sha256 if image else None
        replacement_required = not image and evidence_was_removed(session, case_id)
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
    # Zero is a valid deny/review recommendation, not an invalid refund request.
    checked_amount = recommendation.amount_cents if recommendation.decision == "refund" else case.requested_cents
    checks = blockers(payment, case.requested_cents, checked_amount)
    if recommendation.decision != "refund":
        checks.append("This recommendation requires review or denial; it is not executable.")
    if recommendation.missing_information:
        checks.extend(recommendation.missing_information)
    preview = source == "rule_based_preview" and settings.mode == "preview"
    if preview and not evidence_hash:
        # Deliberately separate simulated workflow from AI-backed proposals.
        checks = blockers(payment, case.requested_cents, recommendation.amount_cents)
    if evidence_hash and source == "rule_based_preview":
        checks.append("Image assessment requires a working Gemini connection; preview cannot verify an attachment.")
    if replacement_required:
        checks.append("Photo evidence was removed. Attach a replacement and analyze it before approval.")
    with Session.begin() as session:
        current = session.get(Case, case_id)
        current_payment = payment_or_404(session, current.payment_id)
        current_image = session.scalar(select(Evidence).where(Evidence.case_id == case_id))
        if current_payment.version != payment.version or (current_image.sha256 if current_image else None) != evidence_hash:
            raise HTTPException(409, "Payment or image evidence changed during analysis. Analyze the current details again.")
        if session.scalar(select(Refund.id).join(Proposal).where(Proposal.case_id == case_id)):
            raise HTTPException(409, "A refund was already approved while this analysis was running.")
        session.execute(update(Proposal).where(Proposal.case_id == case_id, Proposal.state == "ready").values(state="superseded"))
        proposal = Proposal(case_id=case_id, decision="preview" if preview else recommendation.decision, amount_cents=recommendation.amount_cents,
            explanation=recommendation.explanation, citations=[citation.model_dump() for citation in recommendation.citations], blockers=checks,
            source=source, policy_hash=POLICY_HASH, payment_version=payment.version,
            evidence_sha256=evidence_hash, visual_assessment=recommendation.visual_assessment.model_dump() if recommendation.visual_assessment else None,
            fingerprint=fingerprint(case_id, payment.capture_id, recommendation.amount_cents, payment.version, evidence_sha256=evidence_hash), state="blocked" if checks else "ready")
        session.add(proposal)
        current.status = "reviewed"
        session.flush()
        audit(session, "recommendation_created", case_id, proposal_id=proposal.id, source=source, decision=proposal.decision)
        return case_view(session, current)

@app.post("/api/proposals/{proposal_id}/approve")
def approve(proposal_id: str, body: ApprovalInput, _: Auth):
    with Session.begin() as session:
        return approve_proposal(session, proposal_id, confirmed=body.confirmed,
                                reviewed_fingerprint=body.fingerprint, mode=settings.mode)

@app.post("/api/refunds/{refund_id}/reconcile")
def reconcile(refund_id: str, _: Auth):
    with Session.begin() as session:
        operation = session.scalar(select(Refund).where(Refund.id == refund_id).with_for_update())
        if not operation:
            raise HTTPException(404, "Refund operation not found.")
        payment_or_404(session, operation.payment_id)
        if operation.status in {"completed", "failed", "cancelled"}:
            return as_dict(operation)
        job = session.scalar(select(Job).where(Job.reference_id == operation.id))
        if job is None:
            # Repair only the queue entry; retain the original refund payload,
            # reservation and PayPal request ID for idempotent recovery.
            try:
                with session.begin_nested():
                    session.add(Job(kind="refund", reference_id=operation.id))
                    session.flush()
                audit(session, "reconciliation_job_restored", operation_id=operation.id)
            except IntegrityError:
                # A concurrent reconciliation restored the unique job first.
                pass
            job = session.scalar(select(Job).where(Job.reference_id == operation.id))
        if job is None:
            raise HTTPException(503, "The reconciliation job could not be restored. Retry without creating a new refund.")
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
