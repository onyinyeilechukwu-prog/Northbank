"""notification-service: consumes events from a Redis queue and stores notifications."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

import jwt
import redis
from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.events import worker_loop
from app.observability import instrument, setup_logging

SERVICE = "notification"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./notification.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me-please-use-a-32-byte-secret")
REDIS_URL = os.environ.get("REDIS_URL", "")
GROUP = "notification"

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(50))
    event_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    message: Mapped[str] = mapped_column(String(300))


def get_db():
    with SessionLocal() as session:
        yield session


def current_user_id(authorization: str = Header(default="")) -> int:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return int(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="invalid or expired token")


def money(event: dict) -> str:
    return f"{event.get('amount_cents', 0) / 100:.2f}"


def build_message(event: dict) -> str:
    kind = event.get("type", "unknown")
    if kind == "transfer.completed":
        return f"Your transfer of {money(event)} was completed."
    if kind == "transfer.failed":
        return f"Your transfer of {money(event)} failed: {event.get('reason', 'unknown reason')}."
    if kind == "transfer.held":
        return f"Your transfer of {money(event)} is on hold: {event.get('reason', 'under review')}."
    if kind == "kyc.verified":
        return "Your identity was verified. You can now open accounts."
    if kind == "kyc.rejected":
        return "We could not verify your identity. Please contact support."
    if kind == "loan.approved":
        return f"Your loan of {money(event)} was approved and paid into your account."
    if kind == "loan.rejected":
        return f"Your loan application was declined: {event.get('reason', 'see details')}."
    if kind == "card.issued":
        return f"A new card ending {event.get('last4', '????')} was issued."
    if kind == "card.frozen":
        return f"Your card ending {event.get('last4', '????')} was frozen."
    return f"Event received: {kind}"


NOTIFY_ON = {"transfer.completed", "transfer.failed", "transfer.held", "kyc.verified", "kyc.rejected",
             "loan.approved", "loan.rejected", "card.issued", "card.frozen"}


def process_event(db: Session, event: dict) -> Notification | None:
    """Store a notification. Safe to call twice with the same event (at-least-once delivery)."""
    if event.get("type") not in NOTIFY_ON:
        return None  # audit/ledger care about these; the customer does not
    event_id = event.get("event_id")
    if event_id and db.scalar(select(Notification).where(Notification.event_id == event_id)):
        log.info("duplicate event %s ignored", event_id)
        return None
    note = Notification(user_id=int(event["user_id"]), kind=str(event["type"])[:50],
                        message=build_message(event)[:300], event_id=event_id)
    db.add(note)
    db.commit()
    log.info("stored notification id=%s kind=%s", note.id, note.kind)
    return note


def handle_event(event: dict) -> None:
    with SessionLocal() as db:
        process_event(db, event)


def get_redis():
    if not REDIS_URL:
        return None
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    task = asyncio.create_task(worker_loop(get_redis, GROUP, handle_event))
    yield
    task.cancel()


app = FastAPI(title="NorthBank notification-service", lifespan=lifespan)
instrument(app, SERVICE)


@app.get("/ready", tags=["ops"])
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        client = get_redis()
        if client is not None:
            client.ping()
    except Exception as exc:
        log.error("readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="dependency unavailable")
    return {"status": "ready"}


@app.get("/notifications", tags=["notifications"])
def list_notifications(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user_id).order_by(Notification.id.desc())).all()
    return [{"id": n.id, "kind": n.kind, "message": n.message} for n in rows]
