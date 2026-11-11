"""ledger-service: an append-only record of every completed transfer (double entry), plus account statements.

It learns about transfers ONLY from events. It has no direct link to transactions-service, so the two can be
deployed, scaled and fail independently (and ledger catches up from the stream if it was down).
"""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
import jwt
import redis
from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import String, UniqueConstraint, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.events import worker_loop
from app.observability import instrument, setup_logging

SERVICE = "ledger"
GROUP = "ledger"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./ledger.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me-please-use-a-32-byte-secret")
ACCOUNTS_URL = os.environ.get("ACCOUNTS_URL", "http://localhost:8002")
REDIS_URL = os.environ.get("REDIS_URL", "")

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("event_id", "direction", name="uq_event_direction"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[int] = mapped_column(index=True)
    transfer_id: Mapped[int]
    direction: Mapped[str] = mapped_column(String(6))  # debit | credit
    amount_cents: Mapped[int]
    created_at: Mapped[int]


def get_db():
    with SessionLocal() as session:
        yield session


def current_user_id(authorization: str = Header(default="")) -> int:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return int(jwt.decode(token, JWT_SECRET, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="invalid or expired token")


def fetch_account(account_id: int, authorization: str) -> httpx.Response:
    return httpx.get(f"{ACCOUNTS_URL}/accounts/{account_id}", headers={"Authorization": authorization}, timeout=3.0)


def get_redis():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None


def process_event(db: Session, event: dict) -> int:
    """Write the two sides of a completed transfer. Returns how many NEW rows were written (0 on a duplicate)."""
    if event.get("type") != "transfer.completed":
        return 0
    written = 0
    for direction, account in (("debit", event["from_account"]), ("credit", event["to_account"])):
        exists = db.scalar(select(Entry).where(Entry.event_id == event["event_id"], Entry.direction == direction))
        if exists:
            continue
        db.add(Entry(event_id=event["event_id"], account_id=int(account), transfer_id=int(event["transfer_id"]),
                     direction=direction, amount_cents=int(event["amount_cents"]),
                     created_at=int(event.get("occurred_at", time.time()))))
        written += 1
    db.commit()
    return written


def handle_event(event: dict) -> None:
    with SessionLocal() as db:
        process_event(db, event)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    task = asyncio.create_task(worker_loop(get_redis, GROUP, handle_event))
    yield
    task.cancel()


app = FastAPI(title="NorthBank ledger-service", lifespan=lifespan)
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


@app.get("/ledger/accounts/{account_id}/statement", tags=["ledger"])
def statement(account_id: int, authorization: str = Header(default=""),
              _user: int = Depends(current_user_id), db: Session = Depends(get_db)):
    try:
        r = fetch_account(account_id, authorization)  # accounts-service enforces "is this YOUR account?"
    except httpx.HTTPError as exc:
        log.error("accounts-service unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="accounts-service unavailable, try again")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="account not found")
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail="could not verify account, try again")

    rows = db.scalars(select(Entry).where(Entry.account_id == account_id).order_by(Entry.id.desc())).all()
    credits = sum(e.amount_cents for e in rows if e.direction == "credit")
    debits = sum(e.amount_cents for e in rows if e.direction == "debit")
    return {
        "account_id": account_id,
        "total_credits_cents": credits,
        "total_debits_cents": debits,
        "net_cents": credits - debits,
        "entries": [{"transfer_id": e.transfer_id, "direction": e.direction, "amount_cents": e.amount_cents,
                     "at": e.created_at} for e in rows],
    }
