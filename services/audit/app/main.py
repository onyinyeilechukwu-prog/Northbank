"""audit-service: keeps a copy of EVERY event for compliance. It is internal-only (not routed by the gateway)."""
import asyncio
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager

import redis
from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.events import worker_loop
from app.observability import instrument, setup_logging

SERVICE = "audit"
GROUP = "audit"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./audit.db")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token")
REDIS_URL = os.environ.get("REDIS_URL", "")

setup_logging(SERVICE)
log = logging.getLogger(SERVICE)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "audit_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    user_id: Mapped[int | None] = mapped_column(index=True, nullable=True)
    payload: Mapped[str] = mapped_column(Text)
    received_at: Mapped[int]


def get_db():
    with SessionLocal() as session:
        yield session


def require_internal(x_internal_token: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(status_code=403, detail="internal endpoint")


def get_redis():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None


def process_event(db: Session, event: dict) -> Record | None:
    event_id = event.get("event_id")
    if event_id and db.scalar(select(Record).where(Record.event_id == event_id)):
        return None  # duplicate delivery
    record = Record(event_id=event_id, event_type=str(event.get("type", "unknown"))[:50],
                    user_id=event.get("user_id"), payload=json.dumps(event, sort_keys=True),
                    received_at=int(time.time()))
    db.add(record)
    db.commit()
    return record


def handle_event(event: dict) -> None:
    with SessionLocal() as db:
        process_event(db, event)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    task = asyncio.create_task(worker_loop(get_redis, GROUP, handle_event))
    yield
    task.cancel()


app = FastAPI(title="NorthBank audit-service", lifespan=lifespan)
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


@app.get("/audit", tags=["audit"], dependencies=[Depends(require_internal)])
def search(type: str | None = None, user_id: int | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = select(Record).order_by(Record.id.desc()).limit(min(limit, 500))
    if type:
        q = q.where(Record.event_type == type)
    if user_id is not None:
        q = q.where(Record.user_id == user_id)
    return [{"id": r.id, "type": r.event_type, "user_id": r.user_id, "event": json.loads(r.payload)}
            for r in db.scalars(q)]
