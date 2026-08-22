import io


def _upload_csv(client, headers, name="data.csv", content=b"a,b,target\n1,2,3\n4,5,6\n"):
    return client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": (name, io.BytesIO(content), "text/csv")},
    )


def test_upload_dataset_success(client, auth_headers):
    headers, _ = auth_headers
    r = _upload_csv(client, headers)
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "data.csv"
    assert body["rows"] == 2
    assert body["columns"] == 3


def test_upload_rejects_unsupported_extension(client, auth_headers):
    headers, _ = auth_headers
    r = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("data.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "unsupported_file_type"


def test_upload_rejects_empty_file(client, auth_headers):
    headers, _ = auth_headers
    r = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "empty_file"


def test_upload_requires_auth(client):
    r = client.post("/datasets/upload", files={"file": ("data.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert r.status_code == 401


def test_list_datasets_unpaginated_backward_compatible(client, auth_headers):
    headers, _ = auth_headers
    _upload_csv(client, headers, name="one.csv")
    _upload_csv(client, headers, name="two.csv")

    r = client.get("/datasets", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 2


def test_list_datasets_paginated(client, auth_headers):
    headers, _ = auth_headers
    for i in range(3):
        _upload_csv(client, headers, name=f"file{i}.csv")

    r = client.get("/datasets?page=1&page_size=2", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["total_pages"] == 2


def test_delete_dataset(client, auth_headers):
    headers, _ = auth_headers
    upload = _upload_csv(client, headers)
    dataset_id = upload.json()["id"]

    r = client.delete(f"/datasets/{dataset_id}", headers=headers)
    assert r.status_code == 200

    r2 = client.get("/datasets", headers=headers)
    assert r2.json() == []


def test_delete_nonexistent_dataset_returns_404(client, auth_headers):
    headers, _ = auth_headers
    r = client.delete("/datasets/999999", headers=headers)
    assert r.status_code == 404
    assert r.json()["error_code"] == "dataset_not_found"


def test_dataset_isolated_between_users(client, auth_headers):
    headers, _ = auth_headers
    _upload_csv(client, headers)

    client.post("/auth/register", json={"email": "other@example.com", "password": "StrongPass1!"})
    r = client.post("/auth/login", json={"email": "other@example.com", "password": "StrongPass1!"})
    other_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r2 = client.get("/datasets", headers=other_headers)
    assert r2.json() == []


def test_versioned_api_path_mirrors_legacy(client, auth_headers):
    headers, _ = auth_headers
    r = client.get("/api/v1/datasets", headers=headers)
    assert r.status_code == 200
