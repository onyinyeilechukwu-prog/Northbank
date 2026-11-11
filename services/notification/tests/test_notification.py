import os

os.environ["DATABASE_URL"] = "sqlite:///./test_notification.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"

import time  # noqa: E402

import fakeredis  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import events, main  # noqa: E402


def auth(user_id=1):
    now = int(time.time())
    t = jwt.encode({"sub": str(user_id), "iat": now, "exp": now + 3600}, os.environ["JWT_SECRET"], algorithm="HS256")
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def client():
    main.Base.metadata.drop_all(main.engine)
    with TestClient(main.app) as c:
        yield c


def store(event):
    with main.SessionLocal() as db:
        return main.process_event(db, event)


def test_requires_token(client):
    assert client.get("/notifications").status_code == 401


def test_completed_event_becomes_notification(client):
    store({"type": "transfer.completed", "user_id": 1, "amount_cents": 2550})
    assert client.get("/notifications", headers=auth(1)).json()[0]["message"] == "Your transfer of 25.50 was completed."


def test_failed_and_held_messages_include_reason(client):
    store({"type": "transfer.failed", "user_id": 1, "amount_cents": 100, "reason": "insufficient funds"})
    store({"type": "transfer.held", "user_id": 1, "amount_cents": 100, "reason": "held for manual review"})
    text = " ".join(n["message"] for n in client.get("/notifications", headers=auth(1)).json())
    assert "insufficient funds" in text and "manual review" in text


def test_other_event_types_are_ignored(client):
    assert store({"type": "customer.created", "user_id": 1}) is None
    assert client.get("/notifications", headers=auth(1)).json() == []


def test_notifications_are_private_per_user(client):
    store({"type": "transfer.completed", "user_id": 1, "amount_cents": 100})
    assert client.get("/notifications", headers=auth(2)).json() == []


def test_duplicate_event_is_stored_once(client):
    ev = {"event_id": "abc-123", "type": "transfer.completed", "user_id": 1, "amount_cents": 100}
    store(ev)
    store(ev)  # at-least-once delivery: the same event can arrive twice
    assert len(client.get("/notifications", headers=auth(1)).json()) == 1


def test_consumer_reads_from_stream(client):
    redis = fakeredis.FakeRedis(decode_responses=True)
    events.ensure_group(redis, main.GROUP)
    events.publish(redis, events.make_event("transfer.completed", 3, amount_cents=900))
    assert events.consume_once(redis, main.GROUP, "t1", main.handle_event, block_ms=10) == 1
    assert events.consume_once(redis, main.GROUP, "t1", main.handle_event, block_ms=10) == 0  # nothing new
    assert len(client.get("/notifications", headers=auth(3)).json()) == 1


def test_bad_event_is_dropped_not_fatal(client):
    redis = fakeredis.FakeRedis(decode_responses=True)
    events.ensure_group(redis, main.GROUP)
    redis.xadd(events.STREAM, {"data": "this is not json"})
    redis.xadd(events.STREAM, {"data": '{"type": "transfer.completed"}'})  # missing user_id
    assert events.consume_once(redis, main.GROUP, "t1", main.handle_event, block_ms=10) == 2
    assert client.get("/notifications", headers=auth(1)).json() == []
