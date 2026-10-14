"""The MCP server: each tool wrapper delegates to the same tool registry the
chat agent uses, dataset ownership is enforced, and the two action tools
never execute - they only describe what calling them for real would do.
"""

import io

import pytest

import mcp_server
from app import models
from app.database import SessionLocal


SALES_CSV = (
    b"date,region,product,units,price,revenue\n"
    b"2024-01-01,North,Widget,10,100,1000\n"
    b"2024-01-02,South,Gadget,20,50,1000\n"
    b"2024-01-03,East,Widget,15,100,1500\n"
    b"2024-01-04,West,Gadget,25,50,1250\n"
    b"2024-01-05,North,Widget,,100,1000\n"
    b"2024-01-06,South,Gadget,12,50,600\n"
    b"2024-01-07,East,Widget,18,100,1800\n"
    b"2024-01-08,West,Gadget,22,50,1100\n"
)


def _register_and_upload(client, email: str) -> tuple[int, int]:
    client.post(
        "/auth/register",
        json={"email": email, "password": "StrongPass1!", "full_name": "MCP User"},
    )
    tokens = client.post(
        "/auth/login", json={"email": email, "password": "StrongPass1!"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    dataset_id = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("sales.csv", io.BytesIO(SALES_CSV), "text/csv")},
    ).json()["id"]

    db = SessionLocal()
    try:
        dataset = (
            db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        )
        return dataset.owner_id, dataset.id
    finally:
        db.close()


@pytest.fixture
def owned(client, monkeypatch):
    """A dataset belonging to the user INSIGHTFLOW_USER_ID is set to."""
    user_id, dataset_id = _register_and_upload(client, "mcp-owner@example.com")
    monkeypatch.setenv("INSIGHTFLOW_USER_ID", str(user_id))
    return user_id, dataset_id


# ------------------------------------------------------------ authentication


def test_dataset_owned_by_someone_else_is_rejected(client, monkeypatch):
    _owner_id, other_dataset_id = _register_and_upload(client, "mcp-victim@example.com")
    attacker_id, _own_dataset_id = _register_and_upload(
        client, "mcp-attacker@example.com"
    )
    monkeypatch.setenv("INSIGHTFLOW_USER_ID", str(attacker_id))

    result = mcp_server.get_dataset_overview(dataset_id=other_dataset_id)

    assert result["error_code"] == "dataset_not_found"
    assert "profile" not in result


def test_missing_user_id_is_an_error_not_a_crash(client, monkeypatch, owned):
    _user_id, dataset_id = owned
    monkeypatch.delenv("INSIGHTFLOW_USER_ID", raising=False)

    result = mcp_server.get_dataset_overview(dataset_id=dataset_id)

    assert result["error_code"] == "missing_user_id"


def test_unknown_user_id_is_an_error(client, monkeypatch, owned):
    _user_id, dataset_id = owned
    monkeypatch.setenv("INSIGHTFLOW_USER_ID", "999999")

    result = mcp_server.get_dataset_overview(dataset_id=dataset_id)

    assert result["error_code"] == "user_not_found"


# --------------------------------------------------------- read-only tools


def test_get_dataset_overview(owned):
    _user_id, dataset_id = owned
    result = mcp_server.get_dataset_overview(dataset_id=dataset_id)
    assert result["profile"]["rows"] == 8
    assert result["profile"]["columns"] == 6


def test_list_columns(owned):
    _user_id, dataset_id = owned
    result = mcp_server.list_columns(dataset_id=dataset_id)
    assert result["column_count"] == 6
    assert {c["name"] for c in result["columns"]} >= {"revenue", "region"}


def test_profile_column(owned):
    _user_id, dataset_id = owned
    result = mcp_server.profile_column(dataset_id=dataset_id, column="revenue")
    assert result["column"] == "revenue"


def test_profile_column_unknown_column_is_a_registry_error(owned):
    _user_id, dataset_id = owned
    result = mcp_server.profile_column(dataset_id=dataset_id, column="nope")
    assert result["error_code"] == "unknown_column"
    assert "revenue" in result["valid_columns"]


def test_get_correlations(owned):
    _user_id, dataset_id = owned
    result = mcp_server.get_correlations(dataset_id=dataset_id)
    assert "top_pairs" in result


def test_assess_quality(owned):
    _user_id, dataset_id = owned
    result = mcp_server.assess_quality(dataset_id=dataset_id)
    assert set(result) == {"quality", "warnings", "recommendations"}


def test_run_query(owned):
    _user_id, dataset_id = owned
    result = mcp_server.run_query(
        dataset_id=dataset_id, measure="revenue", aggregation="sum", dimension="region"
    )
    assert result["chart_type"] in ("bar", "table")


def test_recommend_cleaning(owned):
    _user_id, dataset_id = owned
    result = mcp_server.recommend_cleaning(dataset_id=dataset_id)
    assert "recommended_config" in result


def test_recommend_targets(owned):
    _user_id, dataset_id = owned
    result = mcp_server.recommend_targets(dataset_id=dataset_id, limit=2)
    assert len(result["candidates"]) <= 2


def test_auto_dashboard(owned):
    _user_id, dataset_id = owned
    result = mcp_server.auto_dashboard(dataset_id=dataset_id)
    assert "kpis" in result and "available" in result


def test_get_model_results_without_a_trained_model(owned):
    _user_id, dataset_id = owned
    result = mcp_server.get_model_results(dataset_id=dataset_id)
    assert result["trained"] is False


def test_explain_model_without_a_trained_model_is_the_registry_error(owned):
    _user_id, dataset_id = owned
    result = mcp_server.explain_model(dataset_id=dataset_id)
    assert result["error_code"] == "no_trained_model"


# -------------------------------------------- action tools: never execute


def test_apply_cleaning_returns_pending_and_changes_nothing(owned):
    user_id, dataset_id = owned

    result = mcp_server.apply_cleaning(dataset_id=dataset_id)

    assert result["status"] == "pending_confirmation"
    assert result["tool_name"] == "apply_cleaning"
    assert "nothing has been changed" in result["note"].lower()

    db = SessionLocal()
    try:
        dataset = (
            db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
        )
        assert dataset.cleaned_path is None
        assert dataset.cleaning_log is None
    finally:
        db.close()


def test_train_model_returns_pending_and_changes_nothing(owned):
    user_id, dataset_id = owned

    result = mcp_server.train_model(dataset_id=dataset_id, target_column="revenue")

    assert result["status"] == "pending_confirmation"
    assert result["tool_name"] == "train_model"
    assert result["arguments"]["target_column"] == "revenue"

    db = SessionLocal()
    try:
        runs = (
            db.query(models.ModelRun)
            .filter(models.ModelRun.dataset_id == dataset_id)
            .all()
        )
        assert runs == []
    finally:
        db.close()


def test_train_model_invalid_arguments_are_rejected_before_a_pending_payload(owned):
    _user_id, dataset_id = owned

    result = mcp_server.train_model(dataset_id=dataset_id, task_type="clustering")

    assert result["error_code"] == "invalid_arguments"
    assert "status" not in result
