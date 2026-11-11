import os

os.environ["DATABASE_URL"] = "sqlite:///./test_auth.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import Base, app, engine  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


def creds(username="alice", password="correct-horse"):
    return {"username": username, "password": password}


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").status_code == 200


def test_register_then_login_returns_valid_token(client):
    assert client.post("/register", json=creds()).status_code == 201
    r = client.post("/login", json=creds())
    assert r.status_code == 200
    claims = jwt.decode(r.json()["access_token"], "test-secret-that-is-at-least-32-bytes-long", algorithms=["HS256"])
    assert claims["username"] == "alice"


def test_duplicate_username_is_rejected(client):
    client.post("/register", json=creds())
    assert client.post("/register", json=creds()).status_code == 409


def test_wrong_password_is_rejected(client):
    client.post("/register", json=creds())
    assert client.post("/login", json=creds(password="wrong-password")).status_code == 401


def test_unknown_user_is_rejected(client):
    assert client.post("/login", json=creds("nobody")).status_code == 401


def test_short_password_fails_validation(client):
    assert client.post("/register", json=creds(password="short")).status_code == 422


def test_metrics_endpoint_exposes_request_counter(client):
    client.get("/health")
    body = client.get("/metrics").text
    assert "http_requests_total" in body
