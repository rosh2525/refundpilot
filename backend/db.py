import time
import uuid
from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings

class Base(DeclarativeBase):
    pass

def uid():
    return str(uuid.uuid4())

url = settings.database_url
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(url, pool_pre_ping=True, **({"connect_args": {"check_same_thread": False, "timeout": 20}} if url.startswith("sqlite") else {"pool_size": 3, "max_overflow": 2}))
if url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
Session = sessionmaker(engine, expire_on_commit=False)

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(String(100), unique=True)
    capture_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    source: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200), default="Northstar desk essentials")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    amount_cents: Mapped[int] = mapped_column(Integer)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="CREATED")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    captured_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    approval_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    capture_request_id: Mapped[str] = mapped_column(String(36), default=uid)

class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"))
    statement: Mapped[str] = mapped_column(Text)
    requested_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="new")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)

class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    decision: Mapped[str] = mapped_column(String(30))
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    explanation: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    blockers: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(50))
    policy_hash: Mapped[str] = mapped_column(String(64))
    payment_version: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(30), default="ready")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)

class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, default=uid)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    paypal_refund_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    reservation_active: Mapped[bool] = mapped_column(Boolean, default=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(30))
    reference_id: Mapped[str] = mapped_column(String(100), unique=True)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    run_after: Mapped[float] = mapped_column(Float, default=time.time)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

class Webhook(Base):
    __tablename__ = "webhooks"
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    verified_at: Mapped[float] = mapped_column(Float, default=time.time)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)

class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    action: Mapped[str] = mapped_column(String(100))
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)

class Quota(Base):
    __tablename__ = "quotas"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)

def audit(session, action, case_id=None, **details):
    session.add(Audit(action=action, case_id=case_id, details=details))

def as_dict(obj):
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}
