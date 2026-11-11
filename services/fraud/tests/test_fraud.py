import os

os.environ["DATABASE_URL"] = "sqlite:///./test_fraud.db"
os.environ["INTERNAL_TOKEN"] = "test-internal"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

H = {"X-Internal-Token": "test-internal"}


def body(amount=1000, user=1):
    return {"user_id": user, "from_account": 1, "to_account": 2, "amount_cents": amount}


@pytest.fixture()
def client():
    main.Base.metadata.drop_all(main.engine)
    with TestClient(main.app) as c:
        yield c


def test_requires_internal_token(client):
    assert client.post("/internal/check", json=body()).status_code == 403
    assert client.get("/internal/decisions").status_code == 403


def test_small_transfer_is_allowed(client):
    r = client.post("/internal/check", json=body(1000), headers=H)
    assert r.json() == {"decision": "allow", "reasons": []}


def test_large_transfer_needs_review(client):
    r = client.post("/internal/check", json=body(2_000_000), headers=H).json()
    assert r["decision"] == "review"


def test_huge_transfer_is_denied(client):
    r = client.post("/internal/check", json=body(9_000_000), headers=H).json()
    assert r["decision"] == "deny" and "limit" in r["reasons"][0]


def test_velocity_rule_denies_the_sixth_rapid_transfer(client):
    results = [client.post("/internal/check", json=body(100), headers=H).json()["decision"] for _ in range(7)]
    assert results[:5] == ["allow"] * 5 and results[5:] == ["deny", "deny"]


def test_velocity_is_per_user(client):
    for _ in range(6):
        client.post("/internal/check", json=body(100, user=1), headers=H)
    assert client.post("/internal/check", json=body(100, user=2), headers=H).json()["decision"] == "allow"


def test_thresholds_are_configurable(client, monkeypatch):
    monkeypatch.setattr(main, "DENY_ABOVE_CENTS", 500)
    assert client.post("/internal/check", json=body(1000), headers=H).json()["decision"] == "deny"


def test_decisions_are_recorded_and_filterable(client):
    client.post("/internal/check", json=body(100, user=1), headers=H)
    client.post("/internal/check", json=body(9_000_000, user=2), headers=H)
    assert len(client.get("/internal/decisions", headers=H).json()) == 2
    only = client.get("/internal/decisions?user_id=2", headers=H).json()
    assert len(only) == 1 and only[0]["decision"] == "deny"


def test_invalid_amount_rejected(client):
    assert client.post("/internal/check", json=body(0), headers=H).status_code == 422
