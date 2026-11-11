"""fraud-service: scores a transfer BEFORE money moves. Returns allow | review | deny with reasons."""
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.observability import instrument, setup_logging

SERVICE = "fraud"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./fraud.db")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token")
# Rules are configuration, not code: tune them per environment without a rebuild.
DENY_ABOVE_CENTS = int(os.environ.get("DENY_ABOVE_CENTS", "5000000"))      # 50,000.00
REVIEW_ABOVE_CENTS = int(os.environ.get("REVIEW_ABOVE_CENTS", "1000000"))  # 10,000.00
VELOCITY_MAX = int(os.environ.get("VELOCITY_MAX", "5"))                    # checks allowed ...
VELOCITY_WINDOW_SECONDS = int(os.environ.get("VELOCITY_WINDOW_SECONDS", "60"))  # ... per window

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    amount_cents: Mapped[int]
    decision: Mapped[str] = mapped_column(String(10))
    reasons: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[int] = mapped_column(index=True)


def get_db():
    with SessionLocal() as session:
        yield session


def require_internal(x_internal_token: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(status_code=403, detail="internal endpoint")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    log.info("fraud-service started")
    yield


app = FastAPI(title="NorthBank fraud-service", lifespan=lifespan)
instrument(app, SERVICE)


class CheckRequest(BaseModel):
    user_id: int
    from_account: int
    to_account: int
    amount_cents: int = Field(gt=0)


@app.get("/ready", tags=["ops"])
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@app.post("/internal/check", tags=["internal"], dependencies=[Depends(require_internal)])
def check(body: CheckRequest, db: Session = Depends(get_db)):
    now = int(time.time())
    recent = db.scalar(
        select(func.count()).select_from(Decision).where(
            Decision.user_id == body.user_id, Decision.created_at > now - VELOCITY_WINDOW_SECONDS
        )
    )
    decision, reasons = "allow", []
    if body.amount_cents > DENY_ABOVE_CENTS:
        decision, reasons = "deny", [f"amount above the {DENY_ABOVE_CENTS / 100:.2f} limit"]
    elif recent >= VELOCITY_MAX:
        decision, reasons = "deny", [f"more than {VELOCITY_MAX} transfers in {VELOCITY_WINDOW_SECONDS}s"]
    elif body.amount_cents > REVIEW_ABOVE_CENTS:
        decision, reasons = "review", ["unusually large amount"]

    db.add(Decision(user_id=body.user_id, amount_cents=body.amount_cents, decision=decision,
                    reasons="; ".join(reasons)[:300], created_at=now))
    db.commit()
    log.info("fraud decision user=%s amount=%s decision=%s", body.user_id, body.amount_cents, decision)
    return {"decision": decision, "reasons": reasons}


@app.get("/internal/decisions", tags=["internal"], dependencies=[Depends(require_internal)])
def decisions(user_id: int | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = select(Decision).order_by(Decision.id.desc()).limit(min(limit, 200))
    if user_id is not None:
        q = q.where(Decision.user_id == user_id)
    return [{"id": d.id, "user_id": d.user_id, "amount_cents": d.amount_cents,
             "decision": d.decision, "reasons": d.reasons} for d in db.scalars(q)]
