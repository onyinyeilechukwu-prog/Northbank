"""loans-service: apply for a loan, instant decision by simple rules, payout via accounts-service, repayments."""
import logging
import os
from contextlib import asynccontextmanager

import httpx
import jwt
import redis
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.events import make_event, publish
from app.observability import instrument, setup_logging

SERVICE = "loans"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./loans.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me-please-use-a-32-byte-secret")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token")
ACCOUNTS_URL = os.environ.get("ACCOUNTS_URL", "http://localhost:8002")
REDIS_URL = os.environ.get("REDIS_URL", "")
MAX_LOAN_CENTS = int(os.environ.get("MAX_LOAN_CENTS", "5000000"))  # 50,000.00
ANNUAL_RATE_BPS = int(os.environ.get("ANNUAL_RATE_BPS", "1200"))   # 12.00% a year (basis points)

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Loan(Base):
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    account_id: Mapped[int]
    principal_cents: Mapped[int]
    term_months: Mapped[int]
    annual_rate_bps: Mapped[int]
    monthly_payment_cents: Mapped[int] = mapped_column(default=0)
    outstanding_cents: Mapped[int] = mapped_column(default=0)  # total still to repay (principal + interest)
    status: Mapped[str] = mapped_column(String(10))  # approved | rejected | repaid
    reason: Mapped[str] = mapped_column(String(200), default="")


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


def credit_account(user_id: int, account_id: int, amount_cents: int) -> httpx.Response:
    return httpx.post(f"{ACCOUNTS_URL}/internal/credit",
                      json={"user_id": user_id, "account_id": account_id, "amount_cents": amount_cents},
                      headers={"X-Internal-Token": INTERNAL_TOKEN}, timeout=5.0)


_redis = None


def get_redis():
    global _redis
    if _redis is None and REDIS_URL:
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def amortization(principal: int, term_months: int, annual_bps: int) -> list[dict]:
    """Equal monthly payments (standard amortizing loan). All values are integer cents."""
    r = annual_bps / 10_000 / 12
    payment = round(principal / term_months) if r == 0 else round(principal * r / (1 - (1 + r) ** -term_months))
    rows, balance = [], principal
    for month in range(1, term_months + 1):
        interest = round(balance * r)
        principal_part = balance if month == term_months else payment - interest
        rows.append({"month": month, "payment_cents": principal_part + interest,
                     "principal_cents": principal_part, "interest_cents": interest,
                     "balance_cents": balance - principal_part})
        balance -= principal_part
    return rows


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    log.info("loans-service started")
    yield


app = FastAPI(title="NorthBank loans-service", lifespan=lifespan)
instrument(app, SERVICE)


class Apply(BaseModel):
    account_id: int
    amount_cents: int = Field(ge=10_000, le=100_000_000)
    term_months: int = Field(ge=3, le=60)


class Repay(BaseModel):
    amount_cents: int = Field(gt=0)


def to_dict(loan: Loan) -> dict:
    return {"id": loan.id, "account_id": loan.account_id, "principal_cents": loan.principal_cents,
            "term_months": loan.term_months, "annual_rate_bps": loan.annual_rate_bps,
            "monthly_payment_cents": loan.monthly_payment_cents, "outstanding_cents": loan.outstanding_cents,
            "status": loan.status, "reason": loan.reason}


def own_loan(db: Session, loan_id: int, user_id: int) -> Loan:
    loan = db.get(Loan, loan_id)
    if not loan or loan.user_id != user_id:
        raise HTTPException(status_code=404, detail="loan not found")
    return loan


@app.get("/ready", tags=["ops"])
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@app.post("/loans", status_code=201, tags=["loans"])
def apply_for_loan(body: Apply, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    reason = ""
    if body.amount_cents > MAX_LOAN_CENTS:
        reason = f"amount above the {MAX_LOAN_CENTS / 100:.2f} limit"
    elif db.scalar(select(Loan).where(Loan.user_id == user_id, Loan.status == "approved")):
        reason = "you already have an active loan"

    loan = Loan(user_id=user_id, account_id=body.account_id, principal_cents=body.amount_cents,
                term_months=body.term_months, annual_rate_bps=ANNUAL_RATE_BPS, status="rejected", reason=reason)

    if not reason:
        schedule = amortization(body.amount_cents, body.term_months, ANNUAL_RATE_BPS)
        # Pay out BEFORE saving as approved. Known gap: if we crash between these two steps the customer has
        # the money but no loan record. Phase 11 asks you to think about how real systems close this window.
        try:
            r = credit_account(user_id, body.account_id, body.amount_cents)
        except httpx.HTTPError as exc:
            log.error("accounts-service unreachable: %s", exc)
            raise HTTPException(status_code=503, detail="accounts-service unavailable, try again")
        if r.status_code in (403, 404):
            raise HTTPException(status_code=r.status_code, detail=r.json().get("detail", "account problem"))
        if r.status_code != 200:
            raise HTTPException(status_code=503, detail="could not pay out the loan, try again")
        loan.status = "approved"
        loan.monthly_payment_cents = schedule[0]["payment_cents"]
        loan.outstanding_cents = sum(row["payment_cents"] for row in schedule)

    db.add(loan)
    db.commit()
    kind = "loan.approved" if loan.status == "approved" else "loan.rejected"
    publish(get_redis(), make_event(kind, user_id, loan_id=loan.id, amount_cents=loan.principal_cents, reason=reason))
    log.info("loan id=%s status=%s", loan.id, loan.status)
    return to_dict(loan)


@app.get("/loans", tags=["loans"])
def list_loans(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    return [to_dict(l) for l in db.scalars(select(Loan).where(Loan.user_id == user_id).order_by(Loan.id))]


@app.get("/loans/{loan_id}/schedule", tags=["loans"])
def schedule(loan_id: int, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    loan = own_loan(db, loan_id, user_id)
    if loan.status == "rejected":
        raise HTTPException(status_code=409, detail="loan was rejected")
    return amortization(loan.principal_cents, loan.term_months, loan.annual_rate_bps)


@app.post("/loans/{loan_id}/repay", tags=["loans"])
def repay(loan_id: int, body: Repay, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    """Records a repayment. Demo limitation: it does not debit an account (a good extension exercise)."""
    loan = own_loan(db, loan_id, user_id)
    if loan.status != "approved":
        raise HTTPException(status_code=409, detail=f"loan is {loan.status}")
    if body.amount_cents > loan.outstanding_cents:
        raise HTTPException(status_code=409, detail="payment is more than the outstanding amount")
    loan.outstanding_cents -= body.amount_cents
    if loan.outstanding_cents == 0:
        loan.status = "repaid"
        publish(get_redis(), make_event("loan.repaid", user_id, loan_id=loan.id))
    db.commit()
    return to_dict(loan)
