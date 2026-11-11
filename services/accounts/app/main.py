"""accounts-service: bank accounts and balances (money is stored as integer cents)."""
import hmac
import logging
import os
from contextlib import asynccontextmanager

import httpx
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.observability import instrument, setup_logging

SERVICE = "accounts"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./accounts.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me-please-use-a-32-byte-secret")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token")
CUSTOMERS_URL = os.environ.get("CUSTOMERS_URL", "")
REQUIRE_KYC = os.environ.get("REQUIRE_KYC", "false").lower() == "true"  # off by default so the demo is easy to try

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    balance_cents: Mapped[int] = mapped_column(default=0)


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


def require_internal(x_internal_token: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(status_code=403, detail="internal endpoint")


def fetch_customer(user_id: int) -> httpx.Response:
    return httpx.get(f"{CUSTOMERS_URL}/internal/customers/{user_id}",
                     headers={"X-Internal-Token": INTERNAL_TOKEN}, timeout=3.0)


def enforce_kyc(user_id: int) -> None:
    """Banks may not open accounts for unverified customers. Fails closed if customers-service is down."""
    if not REQUIRE_KYC:
        return
    try:
        r = fetch_customer(user_id)
    except httpx.HTTPError as exc:
        log.error("customers-service unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="customers-service unavailable, try again")
    if r.status_code == 404:
        raise HTTPException(status_code=403, detail="create your customer profile first")
    if r.status_code >= 500:
        raise HTTPException(status_code=503, detail="customers-service error, try again")
    if r.json().get("kyc_status") != "verified":
        raise HTTPException(status_code=403, detail="identity not verified yet")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    log.info("accounts-service started")
    yield


app = FastAPI(title="NorthBank accounts-service", lifespan=lifespan)
instrument(app, SERVICE)


def to_dict(a: Account) -> dict:
    return {"id": a.id, "owner_id": a.owner_id, "currency": a.currency, "balance_cents": a.balance_cents}


class OpenAccount(BaseModel):
    currency: str = Field(default="USD", min_length=3, max_length=3)


class Deposit(BaseModel):
    amount_cents: int = Field(gt=0, le=100_000_000)


class InternalCredit(BaseModel):
    user_id: int
    account_id: int
    amount_cents: int = Field(gt=0, le=1_000_000_000)


class InternalTransfer(BaseModel):
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


@app.post("/accounts", status_code=201, tags=["accounts"])
def open_account(body: OpenAccount, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    enforce_kyc(user_id)
    account = Account(owner_id=user_id, currency=body.currency.upper())
    db.add(account)
    db.commit()
    log.info("opened account id=%s owner=%s", account.id, user_id)
    return to_dict(account)


@app.get("/accounts", tags=["accounts"])
def list_accounts(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    rows = db.scalars(select(Account).where(Account.owner_id == user_id).order_by(Account.id)).all()
    return [to_dict(a) for a in rows]


@app.get("/accounts/{account_id}", tags=["accounts"])
def get_account(account_id: int, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account or account.owner_id != user_id:
        raise HTTPException(status_code=404, detail="account not found")
    return to_dict(account)


@app.post("/accounts/{account_id}/deposit", tags=["accounts"])
def deposit(account_id: int, body: Deposit, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    """Demo-only funding endpoint. A real bank would never expose this."""
    account = db.get(Account, account_id)
    if not account or account.owner_id != user_id:
        raise HTTPException(status_code=404, detail="account not found")
    account.balance_cents += body.amount_cents
    db.commit()
    return to_dict(account)


@app.post("/internal/transfer", tags=["internal"], dependencies=[Depends(require_internal)])
def internal_transfer(body: InternalTransfer, db: Session = Depends(get_db)):
    """Called by transactions-service only. Debit and credit happen in ONE database transaction."""
    if body.from_account == body.to_account:
        raise HTTPException(status_code=400, detail="cannot transfer to the same account")
    src = db.get(Account, body.from_account)
    dst = db.get(Account, body.to_account)
    if not src or not dst:
        raise HTTPException(status_code=404, detail="account not found")
    if src.owner_id != body.user_id:
        raise HTTPException(status_code=403, detail="source account is not yours")
    if src.currency != dst.currency:
        raise HTTPException(status_code=400, detail="currency mismatch")
    if src.balance_cents < body.amount_cents:
        raise HTTPException(status_code=409, detail="insufficient funds")
    src.balance_cents -= body.amount_cents
    dst.balance_cents += body.amount_cents
    db.commit()
    log.info("transfer applied from=%s to=%s amount=%s", src.id, dst.id, body.amount_cents)
    return {"from_balance_cents": src.balance_cents, "to_balance_cents": dst.balance_cents}


@app.post("/internal/credit", tags=["internal"], dependencies=[Depends(require_internal)])
def internal_credit(body: InternalCredit, db: Session = Depends(get_db)):
    """Used by loans-service to pay out an approved loan into the customer's own account."""
    account = db.get(Account, body.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    if account.owner_id != body.user_id:
        raise HTTPException(status_code=403, detail="account is not yours")
    account.balance_cents += body.amount_cents
    db.commit()
    log.info("credited account=%s amount=%s", account.id, body.amount_cents)
    return to_dict(account)
