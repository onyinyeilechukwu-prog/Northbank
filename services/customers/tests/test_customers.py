import os

os.environ["DATABASE_URL"] = "sqlite:///./test_customers.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"
os.environ["INTERNAL_TOKEN"] = "test-internal"

import json  # noqa: E402
import time  # noqa: E402

import fakeredis  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

INTERNAL = {"X-Internal-Token": "test-internal"}
PROFILE = {"full_name": "Ada Obi", "email": "ada@example.com", "phone": "+2348000000000"}


def auth(user_id=1):
    now = int(time.time())
    t = jwt.encode({"sub": str(user_id), "iat": now, "exp": now + 3600}, os.environ["JWT_SECRET"], algorithm="HS256")
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def env(monkeypatch):
    main.Base.metadata.drop_all(main.engine)
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(main, "get_redis", lambda: redis)
    with TestClient(main.app) as c:
        yield c, redis


def types(redis):
    return [json.loads(f["data"])["type"] for _, f in redis.xrange("northbank.events")]


def test_requires_token(env):
    c, _ = env
    assert c.get("/customers/me").status_code == 401


def test_create_then_read_profile_starts_pending(env):
    c, redis = env
    assert c.post("/customers", json=PROFILE, headers=auth()).status_code == 201
    me = c.get("/customers/me", headers=auth()).json()
    assert me["kyc_status"] == "pending" and me["email"] == "ada@example.com"
    assert types(redis) == ["customer.created"]


def test_duplicate_profile_conflicts(env):
    c, _ = env
    c.post("/customers", json=PROFILE, headers=auth())
    assert c.post("/customers", json=PROFILE, headers=auth()).status_code == 409


def test_validation(env):
    c, _ = env
    assert c.post("/customers", json={**PROFILE, "email": "not-an-email"}, headers=auth()).status_code == 422
    assert c.post("/customers", json={**PROFILE, "full_name": "A"}, headers=auth()).status_code == 422


def test_no_profile_is_404(env):
    c, _ = env
    assert c.get("/customers/me", headers=auth()).status_code == 404


def test_update_profile(env):
    c, _ = env
    c.post("/customers", json=PROFILE, headers=auth())
    r = c.put("/customers/me", json={**PROFILE, "full_name": "Ada Okafor"}, headers=auth())
    assert r.json()["full_name"] == "Ada Okafor"


def test_kyc_update_requires_internal_token_and_publishes(env):
    c, redis = env
    c.post("/customers", json=PROFILE, headers=auth())
    assert c.post("/internal/customers/1/kyc", json={"status": "verified"}).status_code == 403
    r = c.post("/internal/customers/1/kyc", json={"status": "verified"}, headers=INTERNAL)
    assert r.json()["kyc_status"] == "verified"
    assert types(redis) == ["customer.created", "kyc.verified"]
    assert c.get("/internal/customers/1", headers=INTERNAL).json()["kyc_status"] == "verified"


def test_kyc_rejects_unknown_status_and_unknown_user(env):
    c, _ = env
    assert c.post("/internal/customers/1/kyc", json={"status": "verified"}, headers=INTERNAL).status_code == 404
    c.post("/customers", json=PROFILE, headers=auth())
    assert c.post("/internal/customers/1/kyc", json={"status": "maybe"}, headers=INTERNAL).status_code == 422
