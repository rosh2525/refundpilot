import os
import tempfile
from pathlib import Path

_test_directory = tempfile.TemporaryDirectory(prefix="refundpilot-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_test_directory.name) / "test.db")
os.environ["PAYMENT_MODE"] = "preview"
os.environ["WORKER_ENABLED"] = "false"
os.environ["GEMINI_API_KEY"] = ""
os.environ["APP_PASSWORD"] = "refundpilot-local"
os.environ["SESSION_SECRET"] = "local-preview-only-change-before-hosting"
os.environ["APP_URL"] = "http://127.0.0.1:8000"

import pytest
from fastapi.testclient import TestClient
from backend.main import app, login_attempts
from backend.db import Base, engine

@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_attempts.clear()
    yield

@pytest.fixture
def client():
    with TestClient(app) as client:
        response = client.post("/api/session", json={"password": "refundpilot-local"})
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = client.cookies["rp_csrf"]
        yield client

@pytest.fixture
def payment(client):
    return next(p for p in client.get("/api/dashboard").json()["payments"] if p["capture_id"] == "PREVIEW-CAPTURE-001")


def reviewed_case(client, payment, amount=500, statement="The pen holder arrived cracked. Please refund $5 for the damaged item."):
    case = client.post("/api/cases", json={"payment_id": payment["id"], "statement": statement, "requested_cents": amount})
    assert case.status_code == 201, case.text
    response = client.post(f"/api/cases/{case.json()['id']}/analyze")
    assert response.status_code == 200, response.text
    return response.json()


def approved_refund(client, payment, amount=500):
    case = reviewed_case(client, payment, amount)
    proposal = case["proposal"]
    response = client.post(f"/api/proposals/{proposal['id']}/approve", json={"confirmed": True, "fingerprint": proposal["fingerprint"]})
    assert response.status_code == 200, response.text
    return response.json(), case
