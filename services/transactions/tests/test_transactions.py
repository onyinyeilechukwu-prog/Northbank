import json
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_transactions.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"
os.environ["INTERNAL_TOKEN"] = "test-internal"

import time  # noqa: E402

import fakeredis  # noqa: E402
import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402


def auth(user_id=1):
    now = int(time.time())
    t = jwt.encode({"sub": str(user_id), "iat": now, "exp": now + 3600}, os.environ["JWT_SECRET"], algorithm="HS256")
    return {"Authorization": f"Bearer {t}"}


def headers(key="key-12345678", user_id=1):
    return {**auth(user_id), "Idempotency-Key": key}


BODY = {"from_account": 1, "to_account": 2, "amount_cents": 500}


class FakeAccounts:
    """Stands in for accounts-service so these tests need no network."""

    def __init__(self):
        self.calls = 0
        self.status = 200
        self.detail = ""
        self.raise_error = False

    def __call__(self, payload):
        self.calls += 1
        if self.raise_error:
            raise httpx.ConnectError("boom")
        body = {} if self.status == 200 else {"detail": self.detail}
        return httpx.Response(self.status, json=body)


@pytest.fixture()
def env(monkeypatch):
    main.Base.metadata.drop_all(main.engine)
    fake = FakeAccounts()
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(main, "call_accounts", fake)
    monkeypatch.setattr(main, "get_redis", lambda: redis)
    with TestClient(main.app) as c:
        yield c, fake, redis


def test_requires_token(env):
    c, _, _ = env
    assert c.post("/transfers", json=BODY, headers={"Idempotency-Key": "key-12345678"}).status_code == 401


def test_requires_idempotency_key(env):
    c, _, _ = env
    assert c.post("/transfers", json=BODY, headers=auth()).status_code == 400


def test_successful_transfer_publishes_event(env):
    c, fake, redis = env
    r = c.post("/transfers", json=BODY, headers=headers())
    assert r.status_code == 201
    assert r.json()["status"] == "completed"
    entries = redis.xrange("northbank.events")
    assert len(entries) == 1
    event = json.loads(entries[0][1]["data"])
    assert event["type"] == "transfer.completed" and event["user_id"] == 1
    assert event["from_account"] == 1 and event["to_account"] == 2 and event["event_id"]


def test_replay_with_same_key_does_not_move_money_twice(env):
    c, fake, redis = env
    first = c.post("/transfers", json=BODY, headers=headers())
    second = c.post("/transfers", json=BODY, headers=headers())
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert fake.calls == 1
    assert redis.xlen("northbank.events") == 1


def test_rejected_transfer_is_recorded_as_failed(env):
    c, fake, _ = env
    fake.status, fake.detail = 409, "insufficient funds"
    r = c.post("/transfers", json=BODY, headers=headers())
    assert r.status_code == 201
    assert r.json()["status"] == "failed" and r.json()["reason"] == "insufficient funds"


def test_accounts_down_returns_503_and_records_nothing(env):
    c, fake, _ = env
    fake.raise_error = True
    assert c.post("/transfers", json=BODY, headers=headers()).status_code == 503
    assert c.get("/transfers", headers=auth()).json() == []


def test_accounts_5xx_returns_503_and_can_be_retried(env):
    c, fake, _ = env
    fake.status, fake.detail = 500, "oops"
    assert c.post("/transfers", json=BODY, headers=headers()).status_code == 503
    fake.status = 200
    assert c.post("/transfers", json=BODY, headers=headers()).status_code == 201


def test_redis_outage_does_not_fail_the_transfer(env, monkeypatch):
    c, _, _ = env

    class Broken:
        def xadd(self, *a, **k):
            raise ConnectionError("redis down")

    monkeypatch.setattr(main, "get_redis", lambda: Broken())
    assert c.post("/transfers", json=BODY, headers=headers()).status_code == 201


def test_other_users_cannot_reuse_a_key_and_lists_are_private(env):
    c, _, _ = env
    c.post("/transfers", json=BODY, headers=headers(user_id=1))
    assert c.post("/transfers", json=BODY, headers=headers(user_id=2)).status_code == 409
    assert c.get("/transfers", headers=auth(2)).json() == []
    assert len(c.get("/transfers", headers=auth(1)).json()) == 1


def test_validation(env):
    c, _, _ = env
    bad = {**BODY, "amount_cents": 0}
    assert c.post("/transfers", json=bad, headers=headers()).status_code == 422


# ---------- fraud-service integration ----------

class FakeFraud:
    def __init__(self):
        self.decision, self.reasons, self.raise_error, self.status = "allow", [], False, 200

    def __call__(self, payload):
        if self.raise_error:
            raise httpx.ConnectError("fraud down")
        return httpx.Response(self.status, json={"decision": self.decision, "reasons": self.reasons})


@pytest.fixture()
def fraud(env, monkeypatch):
    c, accounts, redis = env
    f = FakeFraud()
    monkeypatch.setattr(main, "FRAUD_URL", "http://fraud")
    monkeypatch.setattr(main, "call_fraud", f)
    return c, accounts, f


def test_fraud_allow_moves_money(fraud):
    c, accounts, f = fraud
    assert c.post("/transfers", json=BODY, headers=headers()).json()["status"] == "completed"
    assert accounts.calls == 1


def test_fraud_deny_blocks_transfer_and_never_calls_accounts(fraud):
    c, accounts, f = fraud
    f.decision, f.reasons = "deny", ["amount too large"]
    r = c.post("/transfers", json=BODY, headers=headers())
    assert r.status_code == 201 and r.json()["status"] == "failed"
    assert "amount too large" in r.json()["reason"]
    assert accounts.calls == 0


def test_fraud_review_holds_transfer(fraud):
    c, accounts, f = fraud
    f.decision, f.reasons = "review", ["unusual amount"]
    r = c.post("/transfers", json=BODY, headers=headers())
    assert r.json()["status"] == "held" and accounts.calls == 0


def test_fraud_down_fails_closed_by_default(fraud):
    c, accounts, f = fraud
    f.raise_error = True
    assert c.post("/transfers", json=BODY, headers=headers()).status_code == 503
    assert accounts.calls == 0


def test_fraud_down_can_fail_open_when_configured(fraud, monkeypatch):
    c, accounts, f = fraud
    f.raise_error = True
    monkeypatch.setattr(main, "FRAUD_FAIL_OPEN", True)
    assert c.post("/transfers", json=BODY, headers=headers()).json()["status"] == "completed"
