"""auth-service: registers users and issues JWT access tokens."""
import hashlib
import hmac
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.observability import instrument, setup_logging

SERVICE = "auth"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./auth.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me-please-use-a-32-byte-secret")
TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "3600"))
HASH_ITERATIONS = 200_000

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)
if JWT_SECRET == "dev-only-change-me-please-use-a-32-byte-secret":
    log.warning("JWT_SECRET is using the insecure development default")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    salt: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))


def get_db():
    with SessionLocal() as session:
        yield session


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), HASH_ITERATIONS
    ).hex()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)  # fine for learning; real teams use migrations
    log.info("auth-service started")
    yield


app = FastAPI(title="NorthBank auth-service", lifespan=lifespan)
instrument(app, SERVICE)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


@app.get("/ready", tags=["ops"])
def ready(db: Session = Depends(get_db)):
    # Readiness: "I can serve traffic", so it DOES check the database.
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@app.post("/register", status_code=201, tags=["auth"])
def register(body: Credentials, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=409, detail="username already taken")
    salt = secrets.token_hex(16)
    user = User(username=body.username, salt=salt, password_hash=hash_password(body.password, salt))
    db.add(user)
    db.commit()
    log.info("registered user id=%s", user.id)
    return {"id": user.id, "username": user.username}


@app.post("/login", tags=["auth"])
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    expected = hash_password(body.password, user.salt) if user else ""
    if not user or not hmac.compare_digest(expected, user.password_hash):
        log.warning("failed login attempt")
        raise HTTPException(status_code=401, detail="invalid username or password")
    now = int(time.time())
    token = jwt.encode(
        {"sub": str(user.id), "username": user.username, "iat": now, "exp": now + TOKEN_TTL_SECONDS},
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"access_token": token, "token_type": "bearer"}
