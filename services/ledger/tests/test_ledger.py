import os

os.environ["DATABASE_URL"] = "sqlite:///./test_ledger.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"

import time  # noqa: E402

import fakeredis  # noqa: E402
import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import events, main  # noqa: E402


def auth(user_id=1):
    now = int(time.time())
    t = jwt.encode({"sub": str(user_id), "iat": now, "exp": now + 3600}, os.environ["JWT_SECRET"], algorithm="HS256")
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def env(monkeypatch):
    main.Base.metadata.drop_all(main.engine)
    acct = {"code": 200, "raise": False}

    def fake_fetch(account_id, authorization):
        if acct["raise"]:
            raise httpx.ConnectError("down")
        return httpx.Response(acct["code"], json={})

    monkeypatch.setattr(main, "fetch_account", fake_fetch)
    with TestClient(main.app) as c:
        yield c, acct


def completed(event_id="e1", amount=2500, transfer_id=1, src=10, dst=20):
    return {"event_id": event_id, "type": "transfer.completed", "user_id": 1, "transfer_id": transfer_id,
            "from_account": src, "to_account": dst, "amount_cents": amount, "occurred_at": 1_700_000_000}


def store(event):
    with main.SessionLocal() as db:
        return main.process_event(db, event)


def test_requires_token(env):
    c, _ = env
    assert c.get("/ledger/accounts/10/statement").status_code == 401


def test_completed_transfer_writes_both_sides(env):
    c, _ = env
    assert store(completed()) == 2
    debit = c.get("/ledger/accounts/10/statement", headers=auth()).json()
    credit = c.get("/ledger/accounts/20/statement", headers=auth()).json()
    assert debit["total_debits_cents"] == 2500 and debit["net_cents"] == -2500
    assert credit["total_credits_cents"] == 2500 and credit["net_cents"] == 2500


def test_duplicate_delivery_does_not_double_count(env):
    c, _ = env
    store(completed())
    assert store(completed()) == 0
    assert len(c.get("/ledger/accounts/10/statement", headers=auth()).json()["entries"]) == 1


def test_failed_and_held_transfers_are_not_ledgered(env):
    for t in ("transfer.failed", "transfer.held", "card.issued"):
        assert store({**completed(), "type": t}) == 0


def test_statement_sums_many_transfers(env):
    c, _ = env
    store(completed("a", 1000, 1))
    store(completed("b", 500, 2))
    store(completed("c", 200, 3, src=20, dst=10))
    s = c.get("/ledger/accounts/10/statement", headers=auth()).json()
    assert s["total_debits_cents"] == 1500 and s["total_credits_cents"] == 200 and s["net_cents"] == -1300


def test_statement_checks_ownership_via_accounts(env):
    c, acct = env
    acct["code"] = 404
    assert c.get("/ledger/accounts/10/statement", headers=auth()).status_code == 404
    acct["code"], acct["raise"] = 200, True
    assert c.get("/ledger/accounts/10/statement", headers=auth()).status_code == 503


def test_consumer_reads_stream_and_survives_poison(env):
    c, _ = env
    redis = fakeredis.FakeRedis(decode_responses=True)
    events.ensure_group(redis, main.GROUP)
    redis.xadd(events.STREAM, {"data": "garbage"})
    events.publish(redis, completed("zz", 700))
    assert events.consume_once(redis, main.GROUP, "t", main.handle_event, block_ms=10) == 2
    assert c.get("/ledger/accounts/10/statement", headers=auth()).json()["total_debits_cents"] == 700
