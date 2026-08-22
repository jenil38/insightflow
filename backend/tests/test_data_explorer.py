"""Dataset detail, row-level preview, column metadata, and CSV export."""
import io

CSV = (
    b"name,region,revenue,signup\n"
    b"acme,north,100.5,2024-01-05\n"
    b"globex,south,250.0,2024-02-11\n"
    b"initech,north,310.25,2024-03-01\n"
    b"umbrella,east,90.0,2024-04-14\n"
    b"stark,west,505.75,2024-05-09\n"
)


def upload(client, headers, content=CSV, name="data.csv", content_type="text/csv"):
    return client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": (name, io.BytesIO(content), content_type)},
    )


def test_dataset_detail_reports_status(client, auth_headers):
    headers, _ = auth_headers
    dataset_id = upload(client, headers).json()["id"]

    r = client.get(f"/datasets/{dataset_id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "data.csv"
    assert body["rows"] == 5
    assert body["has_cleaned_version"] is False
    assert body["active_source"] == "original"
    assert body["model_run_count"] == 0


def test_preview_paginates_and_caps_page_size(client, auth_headers):
    headers, _ = auth_headers
    dataset_id = upload(client, headers).json()["id"]

    r = client.get(f"/datasets/{dataset_id}/preview?page=1&page_size=2", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_rows"] == 5
    assert body["total_pages"] == 3
    assert len(body["rows"]) == 2
    assert body["columns"] == ["name", "region", "revenue", "signup"]
    assert body["source"] == "original"

    # Page 2 returns different rows than page 1.
    page2 = client.get(f"/datasets/{dataset_id}/preview?page=2&page_size=2", headers=headers).json()
    assert page2["rows"] != body["rows"]

    # A page beyond the end clamps to the last page rather than erroring.
    last = client.get(f"/datasets/{dataset_id}/preview?page=99&page_size=2", headers=headers).json()
    assert last["page"] == 3

    # page_size above the server cap is rejected by validation.
    too_big = client.get(f"/datasets/{dataset_id}/preview?page_size=99999", headers=headers)
    assert too_big.status_code == 422


def test_preview_sorting(client, auth_headers):
    headers, _ = auth_headers
    dataset_id = upload(client, headers).json()["id"]

    asc = client.get(
        f"/datasets/{dataset_id}/preview?sort_by=revenue&sort_dir=asc", headers=headers
    ).json()
    desc = client.get(
        f"/datasets/{dataset_id}/preview?sort_by=revenue&sort_dir=desc", headers=headers
    ).json()

    assert [row["revenue"] for row in asc["rows"]] == [90.0, 100.5, 250.0, 310.25, 505.75]
    assert [row["revenue"] for row in desc["rows"]] == [505.75, 310.25, 250.0, 100.5, 90.0]


def test_preview_search_and_unknown_column(client, auth_headers):
    headers, _ = auth_headers
    dataset_id = upload(client, headers).json()["id"]

    found = client.get(f"/datasets/{dataset_id}/preview?search=north", headers=headers).json()
    assert found["total_rows"] == 2

    missing = client.get(f"/datasets/{dataset_id}/preview?search=nothinghere", headers=headers).json()
    assert missing["total_rows"] == 0
    assert missing["rows"] == []

    bad_sort = client.get(f"/datasets/{dataset_id}/preview?sort_by=nope", headers=headers)
    assert bad_sort.status_code == 400
    assert bad_sort.json()["error_code"] == "unknown_column"


def test_preview_search_treats_input_as_literal_not_regex(client, auth_headers):
    """A regex metacharacter must not be interpreted as a pattern."""
    headers, _ = auth_headers
    dataset_id = upload(client, headers).json()["id"]

    r = client.get(f"/datasets/{dataset_id}/preview?search=.%2A", headers=headers)
    assert r.status_code == 200
    # As a literal ".*" this matches nothing; as a regex it would match every row.
    assert r.json()["total_rows"] == 0


def test_columns_metadata_and_single_column_profile(client, auth_headers):
    headers, _ = auth_headers
    dataset_id = upload(client, headers).json()["id"]

    r = client.get(f"/datasets/{dataset_id}/columns", headers=headers)
    assert r.status_code == 200
    columns = {c["column"]: c for c in r.json()["columns"]}
    assert set(columns) == {"name", "region", "revenue", "signup"}
    assert columns["revenue"]["semantic_type"] == "numeric"
    assert columns["signup"]["semantic_type"] == "datetime"

    profile = client.get(f"/datasets/{dataset_id}/columns/revenue", headers=headers)
    assert profile.status_code == 200
    body = profile.json()
    assert body["min"] == 90.0
    assert body["max"] == 505.75
    assert body["missing_count"] == 0
    assert body["histogram"]

    unknown = client.get(f"/datasets/{dataset_id}/columns/nope", headers=headers)
    assert unknown.status_code == 404
    assert unknown.json()["error_code"] == "unknown_column"


def test_csv_export(client, auth_headers):
    headers, _ = auth_headers
    dataset_id = upload(client, headers).json()["id"]

    r = client.get(f"/datasets/{dataset_id}/export", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert b"acme" in r.content


def test_datasets_with_status_listing(client, auth_headers):
    headers, _ = auth_headers
    upload(client, headers, name="one.csv")

    r = client.get("/datasets/with-status", headers=headers)
    assert r.status_code == 200
    row = r.json()[0]
    assert row["filename"] == "one.csv"
    assert row["has_cleaned_version"] is False
    assert row["model_run_count"] == 0


def test_nan_and_infinity_serialize_as_null(client, auth_headers):
    """Invalid JSON literals (NaN/Infinity) would break JSON.parse in the browser."""
    headers, _ = auth_headers
    messy = b"a,b\n1,\n,3\n"
    dataset_id = upload(client, headers, content=messy, name="messy.csv").json()["id"]

    r = client.get(f"/datasets/{dataset_id}/preview", headers=headers)
    assert r.status_code == 200
    assert "NaN" not in r.text and "Infinity" not in r.text
    rows = r.json()["rows"]
    assert rows[0]["b"] is None
    assert rows[1]["a"] is None
