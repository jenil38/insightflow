"""Cross-cutting security tests: ownership isolation, inactive user rejection,
per-user limits, and auth edge cases."""

import io

import pytest


def _register_and_login(client, email="user@example.com", password="StrongPass1!"):
    client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Test"},
    )
    r = client.post("/auth/login", json={"email": email, "password": password})
    tokens = r.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}, tokens


def _upload(client, headers, name="data.csv", content=b"a,b,target\n1,2,3\n4,5,6\n"):
    return client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": (name, io.BytesIO(content), "text/csv")},
    )


class TestInactiveUserRejection:
    def test_inactive_user_cannot_access_protected_routes(self, client):
        headers, _ = _register_and_login(client)

        from tests.conftest import TestingSessionLocal
        from app import models

        db = TestingSessionLocal()
        user = (
            db.query(models.User)
            .filter(models.User.email == "user@example.com")
            .first()
        )
        user.is_active = False
        db.commit()
        db.close()

        r = client.get("/auth/me", headers=headers)
        assert r.status_code == 401
        assert r.json()["error_code"] == "account_disabled"

    def test_inactive_user_cannot_refresh_token(self, client):
        headers, tokens = _register_and_login(client)

        from tests.conftest import TestingSessionLocal
        from app import models

        db = TestingSessionLocal()
        user = (
            db.query(models.User)
            .filter(models.User.email == "user@example.com")
            .first()
        )
        user.is_active = False
        db.commit()
        db.close()

        r = client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert r.status_code == 401


class TestCrossTenantIsolation:
    @pytest.fixture
    def two_users(self, client):
        h1, t1 = _register_and_login(client, "alice@example.com")
        h2, t2 = _register_and_login(client, "bob@example.com")
        upload_r = _upload(client, h1)
        dataset_id = upload_r.json()["id"]
        return h1, h2, dataset_id

    @pytest.mark.parametrize(
        "path_template",
        [
            "/datasets/{id}",
            "/datasets/{id}/preview",
            "/datasets/{id}/columns",
            "/datasets/{id}/profile",
            "/datasets/{id}/quality",
            "/datasets/{id}/dashboard",
            "/datasets/{id}/explain",
            "/datasets/{id}/report",
            "/datasets/{id}/chat/history",
            "/datasets/{id}/chat/suggestions",
            "/datasets/{id}/model/history",
            "/datasets/{id}/train/options",
        ],
    )
    def test_user_cannot_access_other_users_dataset_get(
        self, client, two_users, path_template
    ):
        _, bob_headers, dataset_id = two_users
        path = path_template.format(id=dataset_id)
        r = client.get(path, headers=bob_headers)
        assert r.status_code == 404, f"GET {path} returned {r.status_code}: {r.text}"

    @pytest.mark.parametrize(
        "path_template,body",
        [
            ("/datasets/{id}/train", {}),
            ("/datasets/{id}/clean", {}),
            ("/datasets/{id}/chat", {"question": "What is this?"}),
        ],
    )
    def test_user_cannot_access_other_users_dataset_post(
        self, client, two_users, path_template, body
    ):
        _, bob_headers, dataset_id = two_users
        path = path_template.format(id=dataset_id)
        r = client.post(path, headers=bob_headers, json=body)
        assert r.status_code == 404, f"POST {path} returned {r.status_code}: {r.text}"

    def test_user_cannot_delete_other_users_dataset(self, client, two_users):
        _, bob_headers, dataset_id = two_users
        r = client.delete(f"/datasets/{dataset_id}", headers=bob_headers)
        assert r.status_code == 404


class TestPasswordResetInvalidatesTokens:
    def test_password_reset_revokes_all_refresh_tokens(self, client):
        headers, tokens = _register_and_login(client)

        from tests.conftest import TestingSessionLocal
        from app import models

        db = TestingSessionLocal()
        user = (
            db.query(models.User)
            .filter(models.User.email == "user@example.com")
            .first()
        )
        reset_token = user.reset_token
        db.close()

        if reset_token:
            client.post(
                "/auth/reset-password",
                json={
                    "token": reset_token,
                    "new_password": "NewStrongPass1!",
                },
            )

            r = client.post(
                "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            )
            assert r.status_code == 401


class TestXlsRejected:
    def test_xls_upload_rejected(self, client):
        headers, _ = _register_and_login(client)
        r = client.post(
            "/datasets/upload",
            headers=headers,
            files={
                "file": (
                    "data.xls",
                    io.BytesIO(b"fake xls"),
                    "application/vnd.ms-excel",
                )
            },
        )
        assert r.status_code == 400
        assert r.json()["error_code"] == "unsupported_file_type"
