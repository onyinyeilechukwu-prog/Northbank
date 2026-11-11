"""cards-service: issue virtual cards, freeze/unfreeze/cancel, and authorize card spending."""
import hmac
import logging
import os
import secrets
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

SERVICE = "cards"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./cards.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me-please-use-a-32-byte-secret")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token")
ACCOUNTS_URL = os.environ.get("ACCOUNTS_URL", "http://localhost:8002")
REDIS_URL = os.environ.get("REDIS_URL", "")

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    account_id: Mapped[int]
    last4: Mapped[str] = mapped_column(String(4))  # we NEVER store the full card number (PCI rules)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | frozen | cancelled
    limit_cents: Mapped[int] = mapped_column(default=500_000)  # per-transaction limit


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


def require_internal(x_internal_token: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(status_code=403, detail="internal endpoint")


def fetch_account(account_id: int, authorization: str) -> httpx.Response:
    """Ask accounts-service with the USER'S OWN token, so ownership rules stay in one place."""
    return httpx.get(f"{ACCOUNTS_URL}/accounts/{account_id}", headers={"Authorization": authorization}, timeout=3.0)


_redis = None


def get_redis():
    global _redis
    if _redis is None and REDIS_URL:
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    log.info("cards-service started")
    yield


app = FastAPI(title="NorthBank cards-service", lifespan=lifespan)
instrument(app, SERVICE)


class IssueCard(BaseModel):
    account_id: int
    limit_cents: int = Field(default=500_000, gt=0, le=100_000_000)


class Authorize(BaseModel):
    card_id: int
    amount_cents: int = Field(gt=0)


def to_dict(c: Card) -> dict:
    return {"id": c.id, "account_id": c.account_id, "last4": c.last4, "status": c.status, "limit_cents": c.limit_cents}


def own_card(db: Session, card_id: int, user_id: int) -> Card:
    card = db.get(Card, card_id)
    if not card or card.user_id != user_id:
        raise HTTPException(status_code=404, detail="card not found")
    return card


@app.get("/ready", tags=["ops"])
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@app.post("/cards", status_code=201, tags=["cards"])
def issue_card(body: IssueCard, authorization: str = Header(default=""),
               user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    try:
        r = fetch_account(body.account_id, authorization)
    except httpx.HTTPError as exc:
        log.error("accounts-service unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="accounts-service unavailable, try again")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="account not found")
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail="could not verify account, try again")

    number = "".join(str(secrets.randbelow(10)) for _ in range(16))
    card = Card(user_id=user_id, account_id=body.account_id, last4=number[-4:], limit_cents=body.limit_cents)
    db.add(card)
    db.commit()
    publish(get_redis(), make_event("card.issued", user_id, card_id=card.id, last4=card.last4))
    # The full number is shown exactly once, here, and is not stored anywhere.
    return {**to_dict(card), "card_number": number}


@app.get("/cards", tags=["cards"])
def list_cards(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    return [to_dict(c) for c in db.scalars(select(Card).where(Card.user_id == user_id).order_by(Card.id))]


@app.post("/cards/{card_id}/freeze", tags=["cards"])
def freeze(card_id: int, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    card = own_card(db, card_id, user_id)
    if card.status == "cancelled":
        raise HTTPException(status_code=409, detail="card is cancelled")
    card.status = "frozen"
    db.commit()
    publish(get_redis(), make_event("card.frozen", user_id, card_id=card.id, last4=card.last4))
    return to_dict(card)


@app.post("/cards/{card_id}/unfreeze", tags=["cards"])
def unfreeze(card_id: int, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    card = own_card(db, card_id, user_id)
    if card.status == "cancelled":
        raise HTTPException(status_code=409, detail="card is cancelled")
    card.status = "active"
    db.commit()
    return to_dict(card)


@app.post("/cards/{card_id}/cancel", tags=["cards"])
def cancel(card_id: int, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    card = own_card(db, card_id, user_id)
    card.status = "cancelled"  # permanent: there is deliberately no way back
    db.commit()
    return to_dict(card)


@app.post("/internal/authorize", tags=["internal"], dependencies=[Depends(require_internal)])
def authorize(body: Authorize, db: Session = Depends(get_db)):
    """What a payment network would ask before approving a purchase."""
    card = db.get(Card, body.card_id)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")
    if card.status != "active":
        return {"approved": False, "reason": f"card is {card.status}"}
    if body.amount_cents > card.limit_cents:
        return {"approved": False, "reason": "over the per-transaction limit"}
    return {"approved": True, "reason": ""}
