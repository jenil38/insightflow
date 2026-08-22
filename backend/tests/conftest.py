import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_insightflow.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-not-for-production")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base, get_db
from app.main import app

TEST_DB_PATH = "./test_insightflow.db"
engine = create_engine(f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function", autouse=True)
def fresh_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function", autouse=True)
def reset_rate_limiter():
    # Each test should start with a clean rate-limit bucket - otherwise a test
    # that intentionally exhausts the limit (e.g. test_rate_limit_on_login)
    # would bleed 429s into unrelated tests that reuse the same client IP.
    app.state.limiter.reset()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def registered_user(client):
    payload = {"email": "user@example.com", "password": "StrongPass1!", "full_name": "Test User"}
    client.post("/auth/register", json=payload)
    return payload


@pytest.fixture
def auth_headers(client, registered_user):
    r = client.post("/auth/login", json={"email": registered_user["email"], "password": registered_user["password"]})
    tokens = r.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}, tokens
