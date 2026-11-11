import os

os.environ["DATABASE_URL"] = "sqlite:///./test_accounts.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"
os.environ["INTERNAL_TOKEN"] = "test-internal"

import time  # noqa: E402

import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.main import Base, app, engine  # noqa: E402

INTERNAL = {"X-Internal-Token": "test-internal"}


def token_for(user_id, exp_offset=3600):
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + exp_offset},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def auth(user_id):
    return {"Authorization": f"Bearer {token_for(user_id)}"}


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


def open_funded(client, user_id, cents=0):
    acc = client.post("/accounts", json={}, headers=auth(user_id)).json()
    if cents:
        client.post(f"/accounts/{acc['id']}/deposit", json={"amount_cents": cents}, headers=auth(user_id))
    return acc["id"]


def test_requires_token(client):
    assert client.get("/accounts").status_code == 401


def test_expired_token_rejected(client):
    h = {"Authorization": f"Bearer {token_for(1, exp_offset=-10)}"}
    assert client.get("/accounts", headers=h).status_code == 401


def test_open_list_and_deposit(client):
    acc_id = open_funded(client, 1, 5000)
    rows = client.get("/accounts", headers=auth(1)).json()
    assert [r["balance_cents"] for r in rows] == [5000]
    assert client.get(f"/accounts/{acc_id}", headers=auth(1)).json()["currency"] == "USD"


def test_cannot_see_someone_elses_account(client):
    acc_id = open_funded(client, 1)
    assert client.get(f"/accounts/{acc_id}", headers=auth(2)).status_code == 404


def test_invalid_deposit_amount(client):
    acc_id = open_funded(client, 1)
    r = client.post(f"/accounts/{acc_id}/deposit", json={"amount_cents": -5}, headers=auth(1))
    assert r.status_code == 422


def test_internal_transfer_moves_money_atomically(client):
    a, b = open_funded(client, 1, 10_000), open_funded(client, 2)
    r = client.post(
        "/internal/transfer",
        json={"user_id": 1, "from_account": a, "to_account": b, "amount_cents": 2500},
        headers=INTERNAL,
    )
    assert r.status_code == 200
    assert r.json() == {"from_balance_cents": 7500, "to_balance_cents": 2500}


def test_internal_transfer_insufficient_funds(client):
    a, b = open_funded(client, 1, 100), open_funded(client, 2)
    r = client.post(
        "/internal/transfer",
        json={"user_id": 1, "from_account": a, "to_account": b, "amount_cents": 500},
        headers=INTERNAL,
    )
    assert r.status_code == 409
    assert client.get(f"/accounts/{a}", headers=auth(1)).json()["balance_cents"] == 100


def test_internal_transfer_rejects_wrong_owner_and_missing_token(client):
    a, b = open_funded(client, 1, 1000), open_funded(client, 2)
    body = {"user_id": 2, "from_account": a, "to_account": b, "amount_cents": 10}
    assert client.post("/internal/transfer", json=body, headers=INTERNAL).status_code == 403
    assert client.post("/internal/transfer", json=body).status_code == 403


def test_internal_transfer_same_account_and_unknown_account(client):
    a = open_funded(client, 1, 1000)
    same = {"user_id": 1, "from_account": a, "to_account": a, "amount_cents": 10}
    assert client.post("/internal/transfer", json=same, headers=INTERNAL).status_code == 400
    missing = {"user_id": 1, "from_account": a, "to_account": 999, "amount_cents": 10}
    assert client.post("/internal/transfer", json=missing, headers=INTERNAL).status_code == 404


# ---------- KYC gate ----------

@pytest.fixture()
def kyc(client, monkeypatch):
    state = {"status": "verified", "code": 200, "raise": False}

    def fake(user_id):
        if state["raise"]:
            raise httpx.ConnectError("down")
        body = {"kyc_status": state["status"]} if state["code"] == 200 else {"detail": "no profile"}
        return httpx.Response(state["code"], json=body)

    monkeypatch.setattr(main, "REQUIRE_KYC", True)
    monkeypatch.setattr(main, "fetch_customer", fake)
    return client, state


def test_verified_customer_can_open_account(kyc):
    c, _ = kyc
    assert c.post("/accounts", json={}, headers=auth(1)).status_code == 201


def test_unverified_customer_cannot_open_account(kyc):
    c, state = kyc
    state["status"] = "pending"
    r = c.post("/accounts", json={}, headers=auth(1))
    assert r.status_code == 403 and "not verified" in r.json()["detail"]


def test_missing_profile_cannot_open_account(kyc):
    c, state = kyc
    state["code"] = 404
    assert c.post("/accounts", json={}, headers=auth(1)).status_code == 403


def test_kyc_fails_closed_when_customers_service_is_down(kyc):
    c, state = kyc
    state["raise"] = True
    assert c.post("/accounts", json={}, headers=auth(1)).status_code == 503


# ---------- internal credit ----------

def test_internal_credit_adds_money_for_the_owner(client):
    a = open_funded(client, 1, 100)
    r = client.post("/internal/credit", json={"user_id": 1, "account_id": a, "amount_cents": 900}, headers=INTERNAL)
    assert r.status_code == 200 and r.json()["balance_cents"] == 1000


def test_internal_credit_checks_owner_token_and_account(client):
    a = open_funded(client, 1)
    body = {"user_id": 2, "account_id": a, "amount_cents": 10}
    assert client.post("/internal/credit", json=body, headers=INTERNAL).status_code == 403
    assert client.post("/internal/credit", json={**body, "user_id": 1}).status_code == 403
    assert client.post("/internal/credit", json={**body, "user_id": 1, "account_id": 999}, headers=INTERNAL).status_code == 404
