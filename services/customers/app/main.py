"""customers-service: customer profiles and KYC (know-your-customer) status."""
import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

import jwt
import redis
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.events import make_event, publish
from app.observability import instrument, setup_logging

SERVICE = "customers"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./customers.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me-please-use-a-32-byte-secret")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token")
REDIS_URL = os.environ.get("REDIS_URL", "")

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30), default="")
    kyc_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | verified | rejected


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


_redis = None


def get_redis():
    global _redis
    if _redis is None and REDIS_URL:
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    log.info("customers-service started")
    yield


app = FastAPI(title="NorthBank customers-service", lifespan=lifespan)
instrument(app, SERVICE)

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(pattern=EMAIL, max_length=120)
    phone: str = Field(default="", max_length=30)


class KycUpdate(BaseModel):
    status: Literal["verified", "rejected"]


def to_dict(c: Customer) -> dict:
    return {"user_id": c.user_id, "full_name": c.full_name, "email": c.email,
            "phone": c.phone, "kyc_status": c.kyc_status}


@app.get("/ready", tags=["ops"])
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@app.post("/customers", status_code=201, tags=["customers"])
def create_profile(body: ProfileIn, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    if db.scalar(select(Customer).where(Customer.user_id == user_id)):
        raise HTTPException(status_code=409, detail="profile already exists")
    customer = Customer(user_id=user_id, full_name=body.full_name, email=body.email, phone=body.phone)
    db.add(customer)
    db.commit()
    publish(get_redis(), make_event("customer.created", user_id))
    return to_dict(customer)


@app.get("/customers/me", tags=["customers"])
def my_profile(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    customer = db.scalar(select(Customer).where(Customer.user_id == user_id))
    if not customer:
        raise HTTPException(status_code=404, detail="no profile yet")
    return to_dict(customer)


@app.put("/customers/me", tags=["customers"])
def update_profile(body: ProfileIn, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    customer = db.scalar(select(Customer).where(Customer.user_id == user_id))
    if not customer:
        raise HTTPException(status_code=404, detail="no profile yet")
    customer.full_name, customer.email, customer.phone = body.full_name, body.email, body.phone
    db.commit()
    return to_dict(customer)


@app.get("/internal/customers/{user_id}", tags=["internal"], dependencies=[Depends(require_internal)])
def internal_get(user_id: int, db: Session = Depends(get_db)):
    customer = db.scalar(select(Customer).where(Customer.user_id == user_id))
    if not customer:
        raise HTTPException(status_code=404, detail="no profile")
    return to_dict(customer)


@app.post("/internal/customers/{user_id}/kyc", tags=["internal"], dependencies=[Depends(require_internal)])
def set_kyc(user_id: int, body: KycUpdate, db: Session = Depends(get_db)):
    """Demo stand-in for a compliance officer or an ID-verification provider."""
    customer = db.scalar(select(Customer).where(Customer.user_id == user_id))
    if not customer:
        raise HTTPException(status_code=404, detail="no profile")
    customer.kyc_status = body.status
    db.commit()
    publish(get_redis(), make_event(f"kyc.{body.status}", user_id))
    return to_dict(customer)
