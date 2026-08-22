"""
Training configuration, model history, explainability honesty, and reporting.

The most important assertion in this file is
`test_report_does_not_create_a_new_model_version`: the original code called the
train route function from the report generator, so every PDF download retrained
all candidate models and bumped the model version.
"""

import io

import pytest

# Deterministic, linearly separable-ish data with a clear numeric target and one
# obvious identifier column. 40 rows clears the 20-row training minimum.
ROWS = [
    f"r{i},{'north' if i % 2 else 'south'},{100 + i * 7},{2 * (100 + i * 7) + 15}"
    for i in range(40)
]
CSV = ("row_id,region,spend,revenue\n" + "\n".join(ROWS) + "\n").encode()

FAST_TRAIN = {"enable_tuning": False, "cross_validation_folds": 2, "test_size": 0.25}


@pytest.fixture
def dataset(client, auth_headers):
    headers, _ = auth_headers
    r = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("sales.csv", io.BytesIO(CSV), "text/csv")},
    )
    assert r.status_code == 200
    return r.json()["id"], headers


def train(client, headers, dataset_id, **overrides):
    payload = {**FAST_TRAIN, **overrides}
    return client.post(f"/datasets/{dataset_id}/train", headers=headers, json=payload)


# ---------------------------------------------------------------- config


def test_training_options_offers_real_columns_and_reasons(client, dataset):
    dataset_id, headers = dataset
    r = client.get(f"/datasets/{dataset_id}/train/options", headers=headers)
    assert r.status_code == 200
    body = r.json()

    assert {c["column"] for c in body["columns"]} == {
        "row_id",
        "region",
        "spend",
        "revenue",
    }
    assert body["recommended_target"] is not None
    # Every candidate must justify itself rather than presenting a bare number.
    for candidate in body["target_candidates"]:
        assert candidate["reason"]
        assert 0 < candidate["confidence_pct"] <= 100
    # The identifier column should be suggested for exclusion.
    assert "row_id" in {e["column"] for e in body["suggested_exclusions"]}


def test_train_with_defaults_still_works(client, dataset):
    """An empty body must reproduce the original fully automatic behaviour."""
    dataset_id, headers = dataset
    r = client.post(f"/datasets/{dataset_id}/train", headers=headers, json={})
    assert r.status_code == 200
    body = r.json()
    assert body["best_model"]
    assert body["results"]
    assert body["target_column"]
    assert body["model_version"] == 1


def test_train_honours_explicit_configuration(client, dataset):
    dataset_id, headers = dataset
    r = train(
        client, headers, dataset_id, target_column="revenue", excluded_columns=["spend"]
    )
    assert r.status_code == 200
    body = r.json()
    assert body["target_column"] == "revenue"
    assert body["task_type"] == "regression"
    assert "spend" not in body["features_used"]
    assert body["test_size"] == 0.25
    assert body["cross_validation_folds"] == 2


def test_regression_and_classification_report_only_relevant_metrics(client, dataset):
    dataset_id, headers = dataset

    regression = train(client, headers, dataset_id, target_column="revenue").json()
    metrics = regression["results"][0]["metrics"]
    assert "r2" in metrics and "rmse" in metrics
    assert "f1" not in metrics and "accuracy" not in metrics

    classification = train(
        client, headers, dataset_id, target_column="region", task_type="classification"
    ).json()
    metrics = classification["results"][0]["metrics"]
    assert "f1" in metrics and "accuracy" in metrics
    assert "r2" not in metrics
    assert classification["class_distribution"]


def test_train_rejects_invalid_configuration(client, dataset):
    dataset_id, headers = dataset

    unknown = train(client, headers, dataset_id, target_column="does_not_exist")
    assert unknown.status_code == 400
    assert unknown.json()["error_code"] == "unknown_target_column"

    non_numeric = train(
        client, headers, dataset_id, target_column="region", task_type="regression"
    )
    assert non_numeric.status_code == 400
    assert non_numeric.json()["error_code"] == "non_numeric_regression_target"

    # Out-of-range values are caught by schema validation.
    assert train(client, headers, dataset_id, test_size=0.99).status_code == 422
    assert (
        train(client, headers, dataset_id, cross_validation_folds=1).status_code == 422
    )


def test_insufficient_rows_is_rejected_clearly(client, auth_headers):
    headers, _ = auth_headers
    tiny = b"a,b\n1,2\n3,4\n5,6\n"
    dataset_id = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("tiny.csv", io.BytesIO(tiny), "text/csv")},
    ).json()["id"]

    r = client.post(f"/datasets/{dataset_id}/train", headers=headers, json=FAST_TRAIN)
    assert r.status_code == 400
    assert r.json()["error_code"] == "insufficient_rows"


# --------------------------------------------------------------- history


def test_model_history_and_versioning(client, dataset):
    dataset_id, headers = dataset
    train(client, headers, dataset_id, target_column="revenue")
    train(client, headers, dataset_id, target_column="spend")

    r = client.get(f"/datasets/{dataset_id}/model/history", headers=headers)
    assert r.status_code == 200
    history = r.json()
    assert [run["version"] for run in history] == [2, 1]
    # Reproducibility metadata is persisted with each run.
    assert history[0]["config"]["target_column"] == "spend"
    assert history[0]["features"]
    assert history[0]["rows_used"] > 0
    assert history[0]["has_model_file"] is True


def test_model_download_before_and_after_training(client, dataset):
    dataset_id, headers = dataset

    before = client.get(f"/datasets/{dataset_id}/model/download", headers=headers)
    assert before.status_code == 404
    assert before.json()["error_code"] == "no_trained_model"

    train(client, headers, dataset_id, target_column="revenue")
    after = client.get(f"/datasets/{dataset_id}/model/download", headers=headers)
    assert after.status_code == 200
    assert after.headers["content-type"] == "application/octet-stream"
    assert ".joblib" in after.headers["content-disposition"]
    assert len(after.content) > 0


# ----------------------------------------------------------- explainability


def test_explain_requires_a_trained_model(client, dataset):
    """It must refuse rather than invent a throwaway model, as the original did."""
    dataset_id, headers = dataset
    r = client.get(f"/datasets/{dataset_id}/explain", headers=headers)
    assert r.status_code == 404
    assert r.json()["error_code"] == "no_trained_model"


def test_explain_reports_the_method_it_actually_used(client, dataset):
    dataset_id, headers = dataset
    train(client, headers, dataset_id, target_column="revenue")

    r = client.get(f"/datasets/{dataset_id}/explain", headers=headers)
    assert r.status_code == 200
    body = r.json()

    # The response must never leave the method ambiguous.
    assert body["method"] in {
        "shap",
        "model_feature_importance",
        "coefficients",
        "permutation_importance",
    }
    assert isinstance(body["fallback_used"], bool)
    assert body["fallback_used"] == (body["method"] != "shap")
    if body["fallback_used"]:
        assert body["fallback_reason"], "a fallback must say why SHAP was unavailable"

    # It explains the persisted model, identified explicitly.
    assert body["model_name"]
    assert body["model_version"] == 1
    assert body["target_column"] == "revenue"
    assert body["feature_importance"]
    assert any("not causation" in c or "causation" in c for c in body["caveats"])


def test_explain_describes_the_same_model_that_was_trained(client, dataset):
    dataset_id, headers = dataset
    trained = train(client, headers, dataset_id, target_column="revenue").json()
    explained = client.get(f"/datasets/{dataset_id}/explain", headers=headers).json()

    assert explained["model_name"] == trained["best_model"]
    assert explained["model_version"] == trained["model_version"]
    assert explained["target_column"] == trained["target_column"]


# --------------------------------------------------------------- reporting


def test_report_downloads_as_pdf(client, dataset):
    dataset_id, headers = dataset
    r = client.get(f"/datasets/{dataset_id}/report", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_report_works_without_a_trained_model(client, dataset):
    """Missing sections are handled gracefully instead of failing the download."""
    dataset_id, headers = dataset
    r = client.get(f"/datasets/{dataset_id}/report", headers=headers)
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    # No model was trained, and generating a report must not create one.
    assert (
        client.get(f"/datasets/{dataset_id}/model/history", headers=headers).json()
        == []
    )


def test_report_does_not_create_a_new_model_version(client, dataset):
    """The headline regression: report generation used to retrain every model."""
    dataset_id, headers = dataset
    train(client, headers, dataset_id, target_column="revenue")

    before = client.get(f"/datasets/{dataset_id}/model/history", headers=headers).json()
    assert len(before) == 1

    for _ in range(3):
        assert (
            client.get(f"/datasets/{dataset_id}/report", headers=headers).status_code
            == 200
        )

    after = client.get(f"/datasets/{dataset_id}/model/history", headers=headers).json()
    assert len(after) == 1, "generating a report must not train a new model"
    assert after[0]["version"] == before[0]["version"]


def test_report_history_is_recorded(client, dataset):
    dataset_id, headers = dataset
    assert (
        client.get(f"/datasets/{dataset_id}/report/history", headers=headers).json()
        == []
    )

    client.get(f"/datasets/{dataset_id}/report", headers=headers)
    client.get(f"/datasets/{dataset_id}/report", headers=headers)

    history = client.get(
        f"/datasets/{dataset_id}/report/history", headers=headers
    ).json()
    assert len(history) == 2
    assert all(record["format"] == "pdf" for record in history)


# ------------------------------------------------------------------ agent


def test_agent_pipeline_reports_real_per_step_status(client, dataset):
    dataset_id, headers = dataset
    r = client.post(f"/datasets/{dataset_id}/agent/run", headers=headers)
    assert r.status_code == 200
    body = r.json()

    keys = [s["key"] for s in body["steps"]]
    assert keys == [
        "profile",
        "quality",
        "clean",
        "analytics",
        "train",
        "explain",
        "summarise",
    ]
    for step in body["steps"]:
        assert step["status"] in {"completed", "skipped", "failed"}
        assert step["duration_sec"] is not None
    assert body["steps_completed"] >= 5
    assert body["summary"]["quality_score"] is not None
    assert body["duration_sec"] > 0


def test_agent_continues_when_training_cannot_run(client, auth_headers):
    """A dataset too small to model must still yield profiling and analytics."""
    headers, _ = auth_headers
    tiny = b"a,b\n1,2\n3,4\n5,6\n"
    dataset_id = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("tiny.csv", io.BytesIO(tiny), "text/csv")},
    ).json()["id"]

    r = client.post(f"/datasets/{dataset_id}/agent/run", headers=headers)
    assert r.status_code == 200
    steps = {s["key"]: s for s in r.json()["steps"]}
    assert steps["profile"]["status"] == "completed"
    assert steps["train"]["status"] == "skipped"
    assert steps["train"]["error"]
    # Explain is skipped as a consequence, not failed.
    assert steps["explain"]["status"] == "skipped"


def test_agent_can_skip_optional_stages(client, dataset):
    dataset_id, headers = dataset
    r = client.post(
        f"/datasets/{dataset_id}/agent/run?apply_cleaning=false&train=false",
        headers=headers,
    )
    assert r.status_code == 200
    steps = {s["key"]: s for s in r.json()["steps"]}
    assert steps["clean"]["status"] == "skipped"
    assert steps["train"]["status"] == "skipped"
    assert steps["analytics"]["status"] == "completed"
