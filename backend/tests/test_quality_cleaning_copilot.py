"""
Data-quality scoring, configurable/reversible cleaning, the Copilot, and upload
validation for malformed files.
"""

import io

import pytest

# Deliberately messy: a duplicate row, padded text, mixed date validity,
# a missing numeric, a constant column, and an identifier column.
MESSY = (
    b"id,region,signup,revenue,constant\n"
    b"1, North ,2024-01-05,100.5,x\n"
    b"2,south ,2024-02-11,,x\n"
    b"3,South,not-a-date,310.25,x\n"
    b"4,east,2024-04-14,90.0,x\n"
    b"5,West,2024-05-09,505.75,x\n"
    b"1, North ,2024-01-05,100.5,x\n"
)


@pytest.fixture
def messy_dataset(client, auth_headers):
    headers, _ = auth_headers
    r = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("messy.csv", io.BytesIO(MESSY), "text/csv")},
    )
    assert r.status_code == 200
    return r.json()["id"], headers


# ------------------------------------------------------------ data quality


def test_quality_report_scores_are_explainable(client, messy_dataset):
    dataset_id, headers = messy_dataset
    r = client.get(f"/datasets/{dataset_id}/quality", headers=headers)
    assert r.status_code == 200
    body = r.json()

    quality = body["quality"]
    for key in (
        "overall_score",
        "completeness_score",
        "uniqueness_score",
        "duplicate_score",
        "consistency_score",
    ):
        assert 0 <= quality[key] <= 100

    # Every score must ship the formula behind it - no unexplained "AI score".
    assert set(quality["score_definitions"]) >= {
        "completeness",
        "uniqueness",
        "duplicates",
        "consistency",
        "overall",
    }
    assert quality["grade"] in {"excellent", "good", "fair", "poor"}

    # The overall score must equal its documented weighted formula.
    weights = quality["weights"]
    expected = (
        quality["completeness_score"] * weights["completeness"]
        + quality["duplicate_score"] * weights["duplicates"]
        + quality["consistency_score"] * weights["consistency"]
        + quality["uniqueness_score"] * weights["uniqueness"]
    )
    assert quality["overall_score"] == pytest.approx(expected, abs=0.11)


def test_quality_report_detects_the_real_problems(client, messy_dataset):
    dataset_id, headers = messy_dataset
    body = client.get(f"/datasets/{dataset_id}/quality", headers=headers).json()

    codes = {w["code"] for w in body["warnings"]}
    assert "duplicate_rows" in codes
    assert "constant_columns" in codes
    assert body["quality"]["duplicate_rows"] == 1

    constant_warning = next(
        w for w in body["warnings"] if w["code"] == "constant_columns"
    )
    assert "constant" in constant_warning["columns"]

    # Recommendations must be tied to findings, not generic advice.
    assert body["recommendations"]
    assert all(r["action"] and r["why"] for r in body["recommendations"])
    assert body["data_dictionary"]
    assert body["correlations"] is not None


# ---------------------------------------------------------------- cleaning


def test_cleaning_plan_explains_what_it_would_do(client, messy_dataset):
    dataset_id, headers = messy_dataset
    r = client.get(f"/datasets/{dataset_id}/clean/plan", headers=headers)
    assert r.status_code == 200
    body = r.json()

    assert body["recommended_config"]["remove_duplicates"] is True
    assert body["reasons"]
    assert body["has_cleaned_version"] is False
    # Case standardisation is lossy, so it is never auto-recommended.
    assert body["recommended_config"]["standardize_case"] == "none"


def test_cleaning_preview_changes_nothing_on_disk(client, messy_dataset):
    dataset_id, headers = messy_dataset
    r = client.post(f"/datasets/{dataset_id}/clean/preview", headers=headers, json={})
    assert r.status_code == 200
    body = r.json()

    assert body["before"]["rows"] == 6
    assert body["after"]["rows"] == 5  # the duplicate is dropped
    assert body["preview_rows"]
    assert "destructive" in body

    # Preview must not mark the dataset as cleaned.
    detail = client.get(f"/datasets/{dataset_id}", headers=headers).json()
    assert detail["has_cleaned_version"] is False
    assert detail["active_source"] == "original"


def test_cleaning_apply_then_revert(client, messy_dataset):
    dataset_id, headers = messy_dataset

    applied = client.post(
        f"/datasets/{dataset_id}/clean/apply", headers=headers, json={}
    )
    assert applied.status_code == 200
    assert applied.json()["after"]["rows"] == 5

    detail = client.get(f"/datasets/{dataset_id}", headers=headers).json()
    assert detail["has_cleaned_version"] is True
    assert detail["active_source"] == "cleaned"

    # Downstream reads now see the cleaned data.
    preview = client.get(f"/datasets/{dataset_id}/preview", headers=headers).json()
    assert preview["source"] == "cleaned"
    assert preview["total_rows"] == 5

    reverted = client.post(f"/datasets/{dataset_id}/clean/revert", headers=headers)
    assert reverted.status_code == 200
    assert reverted.json()["reverted"] is True

    detail = client.get(f"/datasets/{dataset_id}", headers=headers).json()
    assert detail["has_cleaned_version"] is False
    # The original row count is intact - the upload was never modified.
    assert (
        client.get(f"/datasets/{dataset_id}/preview", headers=headers).json()[
            "total_rows"
        ]
        == 6
    )


def test_revert_without_cleaning_is_harmless(client, messy_dataset):
    dataset_id, headers = messy_dataset
    r = client.post(f"/datasets/{dataset_id}/clean/revert", headers=headers)
    assert r.status_code == 200
    assert r.json()["reverted"] is False


def test_cleaning_config_is_honoured(client, messy_dataset):
    dataset_id, headers = messy_dataset

    # Opting out of dedupe must keep all rows.
    kept = client.post(
        f"/datasets/{dataset_id}/clean/preview",
        headers=headers,
        json={"config": {"remove_duplicates": False}},
    ).json()
    assert kept["after"]["rows"] == 6

    # Case standardisation is applied only when explicitly requested, and is
    # flagged destructive because it cannot be undone in place.
    lowered = client.post(
        f"/datasets/{dataset_id}/clean/preview",
        headers=headers,
        json={"config": {"standardize_case": "lower"}},
    ).json()
    assert lowered["destructive"] is True
    assert lowered["categories_standardized"] > 0

    # Dropping rows with missing numerics is reflected in the row count.
    dropped = client.post(
        f"/datasets/{dataset_id}/clean/preview",
        headers=headers,
        json={"config": {"numeric_missing_strategy": "drop"}},
    ).json()
    assert dropped["after"]["rows"] < kept["after"]["rows"]


def test_invalid_cleaning_config_is_rejected(client, messy_dataset):
    dataset_id, headers = messy_dataset
    r = client.post(
        f"/datasets/{dataset_id}/clean/preview",
        headers=headers,
        json={"config": {"numeric_missing_strategy": "nonsense"}},
    )
    assert r.status_code == 422


def test_legacy_clean_endpoint_keeps_its_response_keys(client, messy_dataset):
    """The original /clean consumers relied on these exact keys."""
    dataset_id, headers = messy_dataset
    body = client.post(f"/datasets/{dataset_id}/clean", headers=headers, json={}).json()
    for key in (
        "duplicates_removed",
        "missing_values_filled",
        "dates_corrected",
        "categories_standardized",
        "text_columns_normalized",
        "rows_after_cleaning",
        "columns_after_cleaning",
    ):
        assert key in body, f"legacy key {key} disappeared"
    assert body["duplicates_removed"] == 1


# ----------------------------------------------------------------- copilot


def test_copilot_reports_configuration_state_honestly(client, messy_dataset):
    """With no GROQ_API_KEY the UI must be able to show a disabled state."""
    dataset_id, headers = messy_dataset

    suggestions = client.get(
        f"/datasets/{dataset_id}/chat/suggestions", headers=headers
    )
    assert suggestions.status_code == 200
    body = suggestions.json()
    assert body["copilot_enabled"] is False
    assert body["questions"], "suggestions should still be offered"

    health = client.get("/health").json()
    assert health["features"]["copilot"] is False


def test_copilot_ask_without_key_returns_actionable_error(client, messy_dataset):
    dataset_id, headers = messy_dataset
    r = client.post(
        f"/datasets/{dataset_id}/chat",
        headers=headers,
        json={"question": "Summarise this"},
    )
    assert r.status_code == 503
    body = r.json()
    assert body["error_code"] == "copilot_not_configured"
    assert "GROQ_API_KEY" in body["detail"]


def test_copilot_suggestions_reflect_actual_columns(client, messy_dataset):
    dataset_id, headers = messy_dataset
    questions = client.get(
        f"/datasets/{dataset_id}/chat/suggestions", headers=headers
    ).json()["questions"]
    joined = " ".join(questions).lower()
    # This dataset has missing values, so that question is relevant here.
    assert "missing" in joined


def test_chat_history_endpoints(client, messy_dataset):
    dataset_id, headers = messy_dataset
    assert (
        client.get(f"/datasets/{dataset_id}/chat/history", headers=headers).json() == []
    )

    cleared = client.delete(f"/datasets/{dataset_id}/chat/history", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] == 0


def test_question_length_is_validated(client, messy_dataset):
    dataset_id, headers = messy_dataset
    assert (
        client.post(
            f"/datasets/{dataset_id}/chat", headers=headers, json={"question": ""}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/datasets/{dataset_id}/chat",
            headers=headers,
            json={"question": "x" * 5000},
        ).status_code
        == 422
    )


# ------------------------------------------------------- upload validation


@pytest.mark.parametrize(
    "name,content,content_type,expected_code",
    [
        (
            "broken.json",
            b"{not valid json at all",
            "application/json",
            "unparseable_file",
        ),
        (
            "fake.xlsx",
            b"this is not a spreadsheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "unparseable_file",
        ),
        ("headers_only.csv", b"a,b,c\n", "text/csv", "empty_dataset"),
        (
            "script.exe",
            b"MZ\x90\x00",
            "application/octet-stream",
            "unsupported_file_type",
        ),
    ],
)
def test_malformed_uploads_are_rejected(
    client, auth_headers, name, content, content_type, expected_code
):
    headers, _ = auth_headers
    r = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": (name, io.BytesIO(content), content_type)},
    )
    assert r.status_code in (400, 413), r.text
    assert r.json()["error_code"] == expected_code


def test_content_type_mismatch_is_rejected(client, auth_headers):
    headers, _ = auth_headers
    r = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("data.csv", io.BytesIO(b"a,b\n1,2\n"), "image/png")},
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "content_type_mismatch"


def test_oversized_upload_is_rejected(client, auth_headers, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.001)
    headers, _ = auth_headers
    payload = b"a,b\n" + b"1,2\n" * 5000
    r = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("big.csv", io.BytesIO(payload), "text/csv")},
    )
    assert r.status_code == 413
    assert r.json()["error_code"] == "file_too_large"


def test_json_and_excel_uploads_are_supported(client, auth_headers):
    headers, _ = auth_headers

    json_payload = b'[{"a":1,"b":"x"},{"a":2,"b":"y"}]'
    r = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("data.json", io.BytesIO(json_payload), "application/json")},
    )
    assert r.status_code == 200
    assert r.json()["rows"] == 2

    import pandas as pd

    buffer = io.BytesIO()
    pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_excel(buffer, index=False)
    r = client.post(
        "/datasets/upload",
        headers=headers,
        files={
            "file": (
                "data.xlsx",
                io.BytesIO(buffer.getvalue()),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 200
    assert r.json()["rows"] == 3


# ------------------------------------------------------------ user summary


def test_user_summary_is_scoped_to_the_authenticated_user(
    client, auth_headers, messy_dataset
):
    _, headers = messy_dataset

    r = client.get("/users/me/summary", headers=headers)
    assert r.status_code == 200
    mine = r.json()
    assert mine["dataset_count"] == 1
    assert mine["total_rows"] == 6
    assert mine["total_storage_bytes"] > 0

    # A second user sees only their own (empty) totals, not the first user's.
    client.post(
        "/auth/register",
        json={"email": "second@example.com", "password": "StrongPass1!"},
    )
    token = client.post(
        "/auth/login", json={"email": "second@example.com", "password": "StrongPass1!"}
    ).json()["access_token"]
    theirs = client.get(
        "/users/me/summary", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert theirs["dataset_count"] == 0
    assert theirs["total_rows"] == 0


# -------------------------------------------------------------- analytics


def test_analytics_query_validates_statistical_sense(client, messy_dataset):
    dataset_id, headers = messy_dataset

    ok = client.post(
        f"/datasets/{dataset_id}/analytics/query",
        headers=headers,
        json={
            "measure": "revenue",
            "aggregation": "sum",
            "dimension": "region",
            "chart_type": "bar",
        },
    )
    assert ok.status_code == 200
    assert ok.json()["data"]

    # Summing a text column is meaningless and must be refused.
    bad_measure = client.post(
        f"/datasets/{dataset_id}/analytics/query",
        headers=headers,
        json={"measure": "region", "aggregation": "sum", "dimension": "region"},
    )
    assert bad_measure.status_code == 400
    assert bad_measure.json()["error_code"] == "measure_not_numeric"

    # A line chart needs a date column.
    no_date = client.post(
        f"/datasets/{dataset_id}/analytics/query",
        headers=headers,
        json={"measure": "revenue", "chart_type": "line"},
    )
    assert no_date.status_code == 400
    assert no_date.json()["error_code"] == "date_column_required"

    unknown = client.post(
        f"/datasets/{dataset_id}/analytics/query",
        headers=headers,
        json={"measure": "nope", "dimension": "region"},
    )
    assert unknown.status_code == 400
    assert unknown.json()["error_code"] == "unknown_column"


def test_analytics_timeseries_respects_grain(client, messy_dataset):
    dataset_id, headers = messy_dataset
    r = client.post(
        f"/datasets/{dataset_id}/analytics/query",
        headers=headers,
        json={
            "measure": "revenue",
            "aggregation": "sum",
            "date_column": "signup",
            "time_grain": "month",
            "chart_type": "line",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["time_grain"] == "month"
    assert body["data"]
    assert all("period" in point and "value" in point for point in body["data"])
