import os

os.environ["DATABASE_URL"] = "sqlite:///./test_loans.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"

import json  # noqa: E402
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


@pytest.fixture()
def env(monkeypatch):
    main.Base.metadata.drop_all(main.engine)
    redis = fakeredis.FakeRedis(decode_responses=True)
    acct = {"code": 200, "raise": False, "calls": []}

    def fake_credit(user_id, account_id, amount):
        acct["calls"].append((user_id, account_id, amount))
        if acct["raise"]:
            raise httpx.ConnectError("down")
        return httpx.Response(acct["code"], json={"detail": "account problem"})

    monkeypatch.setattr(main, "credit_account", fake_credit)
    monkeypatch.setattr(main, "get_redis", lambda: redis)
    with TestClient(main.app) as c:
        yield c, acct, redis


def apply(c, amount=1_200_000, months=12, user=1):
    return c.post("/loans", json={"account_id": 7, "amount_cents": amount, "term_months": months}, headers=auth(user))


def test_requires_token(env):
    c, _, _ = env
    assert c.get("/loans").status_code == 401


def test_amortization_is_exact_and_pays_off_to_zero():
    rows = main.amortization(1_200_000, 12, 1200)
    assert len(rows) == 12 and rows[-1]["balance_cents"] == 0
    assert sum(r["principal_cents"] for r in rows) == 1_200_000
    assert all(r["payment_cents"] == r["principal_cents"] + r["interest_cents"] for r in rows)
    assert 106_000 < rows[0]["payment_cents"] < 107_000  # about 1,066 a month for 12,000 at 12% over 12 months


def test_zero_interest_loan_splits_evenly():
    rows = main.amortization(1_000_000, 10, 0)
    assert {r["payment_cents"] for r in rows} == {100_000} and rows[-1]["balance_cents"] == 0


def test_approved_loan_is_paid_out_and_published(env):
    c, acct, redis = env
    r = apply(c)
    assert r.status_code == 201 and r.json()["status"] == "approved"
    assert acct["calls"] == [(1, 7, 1_200_000)]
    assert r.json()["outstanding_cents"] > 1_200_000  # principal plus interest
    assert json.loads(redis.xrange("northbank.events")[0][1]["data"])["type"] == "loan.approved"


def test_too_large_loan_is_rejected_without_paying_out(env):
    c, acct, _ = env
    r = apply(c, amount=9_000_000)
    assert r.json()["status"] == "rejected" and "limit" in r.json()["reason"]
    assert acct["calls"] == []


def test_second_active_loan_is_rejected(env):
    c, _, _ = env
    apply(c)
    r = apply(c)
    assert r.json()["status"] == "rejected" and "active loan" in r.json()["reason"]
    assert apply(c, user=2).json()["status"] == "approved"  # a different user is unaffected


def test_accounts_down_means_503_and_no_loan_saved(env):
    c, acct, _ = env
    acct["raise"] = True
    assert apply(c).status_code == 503
    assert c.get("/loans", headers=auth()).json() == []


def test_wrong_account_is_passed_through(env):
    c, acct, _ = env
    acct["code"] = 403
    assert apply(c).status_code == 403


def test_validation(env):
    c, _, _ = env
    assert apply(c, amount=100).status_code == 422
    assert apply(c, months=1).status_code == 422


def test_schedule_and_privacy(env):
    c, _, _ = env
    lid = apply(c).json()["id"]
    assert len(c.get(f"/loans/{lid}/schedule", headers=auth()).json()) == 12
    assert c.get(f"/loans/{lid}/schedule", headers=auth(2)).status_code == 404


def test_repayment_until_repaid(env):
    c, _, redis = env
    loan = apply(c).json()
    lid, total = loan["id"], loan["outstanding_cents"]
    assert c.post(f"/loans/{lid}/repay", json={"amount_cents": total + 1}, headers=auth()).status_code == 409
    c.post(f"/loans/{lid}/repay", json={"amount_cents": total - 100}, headers=auth())
    done = c.post(f"/loans/{lid}/repay", json={"amount_cents": 100}, headers=auth()).json()
    assert done["status"] == "repaid" and done["outstanding_cents"] == 0
    assert c.post(f"/loans/{lid}/repay", json={"amount_cents": 1}, headers=auth()).status_code == 409
    types = [json.loads(f["data"])["type"] for _, f in redis.xrange("northbank.events")]
    assert types == ["loan.approved", "loan.repaid"]
