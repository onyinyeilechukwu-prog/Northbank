import os

os.environ["DATABASE_URL"] = "sqlite:///./test_audit.db"
os.environ["INTERNAL_TOKEN"] = "test-internal"

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import events, main  # noqa: E402

H = {"X-Internal-Token": "test-internal"}


@pytest.fixture()
def client():
    main.Base.metadata.drop_all(main.engine)
    with TestClient(main.app) as c:
        yield c


def store(event):
    with main.SessionLocal() as db:
        return main.process_event(db, event)


def test_requires_internal_token(client):
    assert client.get("/audit").status_code == 403


def test_every_event_type_is_recorded(client):
    store({"event_id": "1", "type": "transfer.completed", "user_id": 1, "amount_cents": 5})
    store({"event_id": "2", "type": "kyc.verified", "user_id": 2})
    store({"event_id": "3", "type": "something.new", "user_id": 3})
    assert len(client.get("/audit", headers=H).json()) == 3


def test_duplicates_are_ignored(client):
    ev = {"event_id": "dup", "type": "card.issued", "user_id": 1}
    assert store(ev) is not None and store(ev) is None
    assert len(client.get("/audit", headers=H).json()) == 1


def test_filters_and_full_payload(client):
    store({"event_id": "1", "type": "loan.approved", "user_id": 1, "amount_cents": 123})
    store({"event_id": "2", "type": "card.issued", "user_id": 2})
    by_type = client.get("/audit?type=loan.approved", headers=H).json()
    assert len(by_type) == 1 and by_type[0]["event"]["amount_cents"] == 123
    assert [r["type"] for r in client.get("/audit?user_id=2", headers=H).json()] == ["card.issued"]


def test_audit_and_notification_style_groups_both_get_every_event(client):
    """Fan-out: two consumer groups on one stream each receive the same event."""
    redis = fakeredis.FakeRedis(decode_responses=True)
    events.ensure_group(redis, "audit")
    events.ensure_group(redis, "some-other-service")
    events.publish(redis, events.make_event("transfer.completed", 1, amount_cents=10))
    seen = []
    assert events.consume_once(redis, "audit", "a", main.handle_event, block_ms=10) == 1
    assert events.consume_once(redis, "some-other-service", "b", seen.append, block_ms=10) == 1
    assert len(client.get("/audit", headers=H).json()) == 1 and len(seen) == 1


def test_poison_message_is_dropped(client):
    redis = fakeredis.FakeRedis(decode_responses=True)
    events.ensure_group(redis, "audit")
    redis.xadd(events.STREAM, {"data": "{not json"})
    assert events.consume_once(redis, "audit", "a", main.handle_event, block_ms=10) == 1
    assert client.get("/audit", headers=H).json() == []
