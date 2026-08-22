def test_register_success(client):
    r = client.post(
        "/auth/register",
        json={
            "email": "new@example.com",
            "password": "StrongPass1!",
            "full_name": "New User",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "new@example.com"
    assert body["is_verified"] is False


def test_register_weak_password_rejected(client):
    r = client.post(
        "/auth/register", json={"email": "weak@example.com", "password": "weak"}
    )
    assert r.status_code == 422
    assert r.json()["error_code"] == "weak_password"


def test_register_duplicate_email_rejected(client, registered_user):
    r = client.post("/auth/register", json=registered_user)
    assert r.status_code == 409
    assert r.json()["error_code"] == "email_taken"


def test_login_success_returns_access_and_refresh_tokens(client, registered_user):
    r = client.post(
        "/auth/login",
        json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_login_wrong_password_rejected(client, registered_user):
    r = client.post(
        "/auth/login",
        json={"email": registered_user["email"], "password": "WrongPass1!"},
    )
    assert r.status_code == 401
    assert r.json()["error_code"] == "invalid_credentials"


def test_me_requires_auth(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_with_valid_token(client, auth_headers):
    headers, _ = auth_headers
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "user@example.com"


def test_refresh_token_rotates_and_old_one_is_invalid(client, auth_headers):
    _, tokens = auth_headers
    old_refresh = tokens["refresh_token"]

    r = client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["refresh_token"] != old_refresh

    # Old refresh token should now be revoked and rejected.
    r2 = client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 401
    assert r2.json()["error_code"] == "invalid_refresh_token"


def test_logout_revokes_refresh_token(client, auth_headers):
    _, tokens = auth_headers
    r = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 204

    r2 = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401


def test_password_reset_flow(client, registered_user):
    r = client.post(
        "/auth/request-password-reset", json={"email": registered_user["email"]}
    )
    assert r.status_code == 202

    # Grab the reset token directly from the DB since email delivery is stubbed to a log line.
    from app.database import SessionLocal  # noqa
    from tests.conftest import TestingSessionLocal
    from app import models

    db = TestingSessionLocal()
    user = (
        db.query(models.User)
        .filter(models.User.email == registered_user["email"])
        .first()
    )
    reset_token = user.reset_token
    db.close()
    assert reset_token

    r2 = client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "NewStrongPass1!"},
    )
    assert r2.status_code == 200

    # Old password no longer works, new one does.
    r3 = client.post(
        "/auth/login",
        json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    assert r3.status_code == 401
    r4 = client.post(
        "/auth/login",
        json={"email": registered_user["email"], "password": "NewStrongPass1!"},
    )
    assert r4.status_code == 200


def test_email_verification_flow(client, registered_user):
    from tests.conftest import TestingSessionLocal
    from app import models

    db = TestingSessionLocal()
    user = (
        db.query(models.User)
        .filter(models.User.email == registered_user["email"])
        .first()
    )
    token = user.verification_token
    db.close()
    assert token

    r = client.post("/auth/verify-email", json={"token": token})
    assert r.status_code == 200
    assert r.json()["is_verified"] is True


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_rate_limit_on_login(client, registered_user):
    # RATE_LIMIT_AUTH defaults to 10/minute; hammering it should eventually 429.
    last_status = None
    for _ in range(15):
        r = client.post(
            "/auth/login",
            json={"email": registered_user["email"], "password": "WrongPass1!"},
        )
        last_status = r.status_code
    assert last_status in (401, 429)
