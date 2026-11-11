import os

os.environ["DATABASE_URL"] = "sqlite:///./test_cards.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"
os.environ["INTERNAL_TOKEN"] = "test-internal"

import json  # noqa: E402
import time  # noqa: E402

import fakeredis  # noqa: E402
import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

INTERNAL = {"X-Internal-Token": "test-internal"}


def auth(user_id=1):
    now = int(time.time())
    t = jwt.encode({"sub": str(user_id), "iat": now, "exp": now + 3600}, os.environ["JWT_SECRET"], algorithm="HS256")
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def env(monkeypatch):
    main.Base.metadata.drop_all(main.engine)
    redis = fakeredis.FakeRedis(decode_responses=True)
    acct = {"code": 200, "raise": False, "seen_auth": None}

    def fake_fetch(account_id, authorization):
        acct["seen_auth"] = authorization
        if acct["raise"]:
            raise httpx.ConnectError("down")
        return httpx.Response(acct["code"], json={"id": account_id})

    monkeypatch.setattr(main, "fetch_account", fake_fetch)
    monkeypatch.setattr(main, "get_redis", lambda: redis)
    with TestClient(main.app) as c:
        yield c, acct, redis


def issue(c, user=1, **extra):
    return c.post("/cards", json={"account_id": 7, **extra}, headers=auth(user))


def test_requires_token(env):
    c, _, _ = env
    assert c.get("/cards").status_code == 401


def test_issue_card_shows_number_once_and_stores_only_last4(env):
    c, acct, redis = env
    r = issue(c)
    assert r.status_code == 201
    number = r.json()["card_number"]
    assert len(number) == 16 and number.isdigit() and r.json()["last4"] == number[-4:]
    listed = c.get("/cards", headers=auth()).json()
    assert "card_number" not in listed[0] and listed[0]["last4"] == number[-4:]
    assert json.loads(redis.xrange("northbank.events")[0][1]["data"])["type"] == "card.issued"
    assert acct["seen_auth"].startswith("Bearer ")  # the user's own token was forwarded


def test_cannot_issue_for_someone_elses_or_missing_account(env):
    c, acct, _ = env
    acct["code"] = 404
    assert issue(c).status_code == 404


def test_issue_503_when_accounts_down(env):
    c, acct, _ = env
    acct["raise"] = True
    assert issue(c).status_code == 503


def test_freeze_unfreeze_cancel_lifecycle(env):
    c, _, redis = env
    cid = issue(c).json()["id"]
    assert c.post(f"/cards/{cid}/freeze", headers=auth()).json()["status"] == "frozen"
    assert c.post(f"/cards/{cid}/unfreeze", headers=auth()).json()["status"] == "active"
    assert c.post(f"/cards/{cid}/cancel", headers=auth()).json()["status"] == "cancelled"
    assert c.post(f"/cards/{cid}/unfreeze", headers=auth()).status_code == 409
    assert c.post(f"/cards/{cid}/freeze", headers=auth()).status_code == 409


def test_users_cannot_touch_each_others_cards(env):
    c, _, _ = env
    cid = issue(c, user=1).json()["id"]
    assert c.post(f"/cards/{cid}/freeze", headers=auth(2)).status_code == 404
    assert c.get("/cards", headers=auth(2)).json() == []


def test_authorize_rules(env):
    c, _, _ = env
    cid = issue(c, limit_cents=10_000).json()["id"]
    ok = lambda amt: c.post("/internal/authorize", json={"card_id": cid, "amount_cents": amt}, headers=INTERNAL).json()  # noqa: E731
    assert ok(5000)["approved"] is True
    assert ok(20_000) == {"approved": False, "reason": "over the per-transaction limit"}
    c.post(f"/cards/{cid}/freeze", headers=auth())
    assert ok(100) == {"approved": False, "reason": "card is frozen"}


def test_authorize_needs_internal_token_and_known_card(env):
    c, _, _ = env
    assert c.post("/internal/authorize", json={"card_id": 1, "amount_cents": 1}).status_code == 403
    assert c.post("/internal/authorize", json={"card_id": 99, "amount_cents": 1}, headers=INTERNAL).status_code == 404
