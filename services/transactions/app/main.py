"""transactions-service: money transfers with idempotency, calling accounts-service."""
import logging
import os
from contextlib import asynccontextmanager

import httpx
import jwt
import redis
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.events import make_event, publish
from app.observability import instrument, setup_logging

SERVICE = "transactions"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./transactions.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me-please-use-a-32-byte-secret")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token")
ACCOUNTS_URL = os.environ.get("ACCOUNTS_URL", "http://localhost:8002")
REDIS_URL = os.environ.get("REDIS_URL", "")
FRAUD_URL = os.environ.get("FRAUD_URL", "")  # empty = fraud check disabled
FRAUD_FAIL_OPEN = os.environ.get("FRAUD_FAIL_OPEN", "false").lower() == "true"

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Transfer(Base):
    __tablename__ = "transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    from_account: Mapped[int]
    to_account: Mapped[int]
    amount_cents: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))  # completed | failed | held
    reason: Mapped[str] = mapped_column(String(200), default="")


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


_redis = None


def get_redis():
    """Return a Redis client, or None when REDIS_URL is not configured."""
    global _redis
    if _redis is None and REDIS_URL:
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def publish_event(event: dict) -> None:
    publish(get_redis(), event)


def call_fraud(payload: dict) -> httpx.Response:
    return httpx.post(
        f"{FRAUD_URL}/internal/check",
        json=payload,
        headers={"X-Internal-Token": INTERNAL_TOKEN},
        timeout=3.0,
    )


def call_accounts(payload: dict) -> httpx.Response:
    return httpx.post(
        f"{ACCOUNTS_URL}/internal/transfer",
        json=payload,
        headers={"X-Internal-Token": INTERNAL_TOKEN},
        timeout=5.0,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    log.info("transactions-service started")
    yield


app = FastAPI(title="NorthBank transactions-service", lifespan=lifespan)
instrument(app, SERVICE)


class TransferRequest(BaseModel):
    from_account: int
    to_account: int
    amount_cents: int = Field(gt=0, le=100_000_000)


def to_dict(t: Transfer) -> dict:
    return {
        "id": t.id,
        "from_account": t.from_account,
        "to_account": t.to_account,
        "amount_cents": t.amount_cents,
        "status": t.status,
        "reason": t.reason,
    }


@app.get("/ready", tags=["ops"])
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@app.post("/transfers", status_code=201, tags=["transfers"])
def create_transfer(
    body: TransferRequest,
    response: Response,
    idempotency_key: str = Header(default=""),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    if not (8 <= len(idempotency_key) <= 100):
        raise HTTPException(status_code=400, detail="Idempotency-Key header (8-100 chars) is required")

    existing = db.scalar(select(Transfer).where(Transfer.idempotency_key == idempotency_key))
    if existing:
        if existing.user_id != user_id:
            raise HTTPException(status_code=409, detail="idempotency key already used")
        response.status_code = 200  # replay: same answer, money NOT moved twice
        return to_dict(existing)

    status, reason = "completed", ""

    if FRAUD_URL:
        try:
            fr = call_fraud({"user_id": user_id, "from_account": body.from_account,
                             "to_account": body.to_account, "amount_cents": body.amount_cents})
            if fr.status_code >= 500:
                raise httpx.HTTPError(f"fraud-service returned {fr.status_code}")
            verdict = fr.json()
        except httpx.HTTPError as exc:
            log.error("fraud-service problem: %s", exc)
            if not FRAUD_FAIL_OPEN:
                raise HTTPException(status_code=503, detail="fraud-service unavailable, try again")
            verdict = {"decision": "allow", "reasons": ["fraud check skipped (fail-open)"]}
        if verdict["decision"] == "deny":
            status, reason = "failed", "blocked by fraud check: " + "; ".join(verdict.get("reasons", []))
        elif verdict["decision"] == "review":
            status, reason = "held", "held for manual review: " + "; ".join(verdict.get("reasons", []))

    if status == "completed":
        try:
            r = call_accounts(
                {
                    "user_id": user_id,
                    "from_account": body.from_account,
                    "to_account": body.to_account,
                    "amount_cents": body.amount_cents,
                }
            )
        except httpx.HTTPError as exc:
            log.error("accounts-service unreachable: %s", exc)
            raise HTTPException(status_code=503, detail="accounts-service unavailable, try again")

        if r.status_code >= 500:
            raise HTTPException(status_code=503, detail="accounts-service error, try again")

        if r.status_code != 200:
            status, reason = "failed", str(r.json().get("detail", "rejected"))[:200]

    transfer = Transfer(
        user_id=user_id,
        idempotency_key=idempotency_key,
        from_account=body.from_account,
        to_account=body.to_account,
        amount_cents=body.amount_cents,
        status=status,
        reason=reason[:200],
    )
    db.add(transfer)
    db.commit()
    log.info("transfer id=%s status=%s", transfer.id, status)

    publish_event(
        make_event(
            f"transfer.{status}", user_id, transfer_id=transfer.id,
            from_account=body.from_account, to_account=body.to_account,
            amount_cents=body.amount_cents, reason=reason,
        )
    )
    return to_dict(transfer)


@app.get("/transfers", tags=["transfers"])
def list_transfers(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    rows = db.scalars(select(Transfer).where(Transfer.user_id == user_id).order_by(Transfer.id.desc())).all()
    return [to_dict(t) for t in rows]
