"""The agent's tool registry: schemas, argument validation, and failure modes.

These exercise `execute_tool` directly rather than through the agent loop, which
does not exist yet. The loop is what records a step; the registry is what
decides whether a call is allowed, valid, and what it returns, so that is tested
here on its own.
"""

import io

import pytest

from app.database import SessionLocal
from app.services.tool_registry import (
    STATUS_BLOCKED_ACTION,
    STATUS_INVALID_ARGUMENTS,
    STATUS_OK,
    STATUS_TOOL_ERROR,
    STATUS_UNKNOWN_TOOL,
    TOOLS,
    ToolContext,
    execute_tool,
    tools_for,
    tools_schema,
)
from app import models
from app.core.config import settings

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


@pytest.fixture
def uploaded(client):
    """A real dataset row plus a session, since tools take a Dataset and a db."""
    client.post(
        "/auth/register",
        json={
            "email": "tools@example.com",
            "password": "StrongPass1!",
            "full_name": "Tool User",
        },
    )
    tokens = client.post(
        "/auth/login",
        json={"email": "tools@example.com", "password": "StrongPass1!"},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    dataset_id = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("sales.csv", io.BytesIO(SALES_CSV), "text/csv")},
    ).json()["id"]

    db = SessionLocal()
    dataset = db.query(models.Dataset).filter(models.Dataset.id == dataset_id).first()
    user_id = dataset.owner_id
    try:
        yield db, dataset, user_id
    finally:
        db.close()


@pytest.fixture
def ctx(uploaded):
    db, dataset, user_id = uploaded
    return ToolContext(db=db, dataset=dataset, user_id=user_id, allow_actions=False)


@pytest.fixture
def action_ctx(uploaded):
    db, dataset, user_id = uploaded
    return ToolContext(db=db, dataset=dataset, user_id=user_id, allow_actions=True)


# ----------------------------------------------------------------- schemas


def test_eleven_tools_are_registered():
    assert len(TOOLS) == 11
    assert len([t for t in TOOLS if t.read_only]) == 9
    assert sorted(t.name for t in TOOLS if not t.read_only) == [
        "apply_cleaning",
        "train_model",
    ]


def test_action_tools_are_omitted_when_actions_are_not_allowed():
    names = {t.name for t in tools_for(allow_actions=False)}
    assert "apply_cleaning" not in names
    assert "train_model" not in names
    assert len(names) == 9

    allowed = {t.name for t in tools_for(allow_actions=True)}
    assert "apply_cleaning" in allowed and "train_model" in allowed


def test_schema_is_shaped_for_the_provider():
    schema = tools_schema(allow_actions=True)
    assert len(schema) == 11
    entry = next(s for s in schema if s["function"]["name"] == "run_query")

    assert entry["type"] == "function"
    assert entry["function"]["description"]
    params = entry["function"]["parameters"]
    assert params["type"] == "object"
    assert params["additionalProperties"] is False
    assert "measure" in params["properties"]
    # Literal choices must reach the model, or it has to guess them.
    assert set(params["properties"]["aggregation"]["enum"]) == {
        "sum",
        "avg",
        "count",
        "min",
        "max",
        "median",
    }


def test_no_tool_exposes_a_dataset_id_or_use_cleaned():
    """Scoping is structural: the model must not be able to pick the dataset,
    nor which copy of it is read."""
    for tool in TOOLS:
        properties = tool.args_model.model_json_schema().get("properties", {})
        assert "dataset_id" not in properties, tool.name
        assert "use_cleaned" not in properties, tool.name


# ------------------------------------------------------- dispatch failures


def test_unknown_tool_is_rejected_and_lists_what_exists(ctx):
    outcome = execute_tool(ctx, "delete_everything", {})

    assert outcome.status == STATUS_UNKNOWN_TOOL
    assert outcome.error_code == "unknown_tool"
    assert "get_dataset_overview" in outcome.error


def test_action_tool_is_blocked_without_permission(ctx):
    outcome = execute_tool(ctx, "apply_cleaning", {})

    assert outcome.status == STATUS_BLOCKED_ACTION
    assert outcome.error_code == "action_not_permitted"
    # Nothing was written.
    assert ctx.dataset.cleaned_path is None


def test_invented_argument_is_rejected_not_ignored(ctx):
    outcome = execute_tool(ctx, "get_dataset_overview", {"dataset_id": 999})

    assert outcome.status == STATUS_INVALID_ARGUMENTS
    assert outcome.error_code == "invalid_arguments"
    assert "dataset_id" in outcome.error


def test_wrong_argument_type_is_reported(ctx):
    outcome = execute_tool(ctx, "run_query", {"top_n": "lots"})

    assert outcome.status == STATUS_INVALID_ARGUMENTS
    assert "top_n" in outcome.error


def test_out_of_range_argument_is_reported(ctx):
    outcome = execute_tool(ctx, "run_query", {"top_n": 5000})

    assert outcome.status == STATUS_INVALID_ARGUMENTS
    assert "top_n" in outcome.error


def test_missing_required_argument_is_reported(ctx):
    outcome = execute_tool(ctx, "profile_column", {})

    assert outcome.status == STATUS_INVALID_ARGUMENTS
    assert "column" in outcome.error


def test_non_object_arguments_are_rejected(ctx):
    outcome = execute_tool(ctx, "get_dataset_overview", ["not", "an", "object"])

    assert outcome.status == STATUS_INVALID_ARGUMENTS
    assert outcome.error_code == "arguments_not_an_object"


def test_omitted_arguments_are_treated_as_empty(ctx):
    assert execute_tool(ctx, "get_dataset_overview", None).status == STATUS_OK


# ------------------------------------------------------------ read-only tools


def test_dataset_overview_returns_shape_and_quality(ctx):
    outcome = execute_tool(ctx, "get_dataset_overview", {})

    assert outcome.status == STATUS_OK
    assert outcome.value["profile"]["rows"] == 8
    assert outcome.value["profile"]["columns"] == 6
    assert 0 <= outcome.value["quality"]["overall_score"] <= 100


def test_profile_column_works_and_unknown_column_returns_the_valid_names(ctx):
    good = execute_tool(ctx, "profile_column", {"column": "revenue"})
    assert good.status == STATUS_OK
    assert good.value["column"] == "revenue"

    bad = execute_tool(ctx, "profile_column", {"column": "revenu"})
    assert bad.status == STATUS_TOOL_ERROR
    assert bad.error_code == "unknown_column"
    # The model can only fix this if it is told what does exist.
    assert "revenue" in bad.value["valid_columns"]


def test_run_query_groups_by_a_dimension(ctx):
    outcome = execute_tool(
        ctx,
        "run_query",
        {"measure": "revenue", "aggregation": "sum", "dimension": "region"},
    )

    assert outcome.status == STATUS_OK
    assert outcome.value["chart_type"] in ("bar", "table")


def test_run_query_refusal_reaches_the_model_with_its_reason(ctx):
    """A sum over a text column is refused by AnalyticsService._validate, and
    that reason is better feedback than anything the registry could invent."""
    outcome = execute_tool(
        ctx, "run_query", {"measure": "region", "aggregation": "sum"}
    )

    assert outcome.status == STATUS_TOOL_ERROR
    assert outcome.error_code == "measure_not_numeric"
    assert "region" in outcome.error


def test_correlations_and_quality_and_cleaning_plan_are_read_only(ctx):
    for name in ("get_correlations", "assess_quality", "recommend_cleaning"):
        assert execute_tool(ctx, name, {}).status == STATUS_OK, name
    assert ctx.dataset.cleaned_path is None


def test_assess_quality_returns_only_the_three_relevant_sections(ctx):
    outcome = execute_tool(ctx, "assess_quality", {})

    assert outcome.status == STATUS_OK
    assert set(outcome.value) == {"quality", "warnings", "recommendations"}


def test_model_results_without_training_says_so_instead_of_failing(ctx):
    outcome = execute_tool(ctx, "get_model_results", {})

    assert outcome.status == STATUS_OK
    assert outcome.value["trained"] is False


def test_explain_without_a_model_is_an_actionable_error(ctx):
    outcome = execute_tool(ctx, "explain_model", {})

    assert outcome.status == STATUS_TOOL_ERROR
    assert outcome.error_code == "no_trained_model"


# --------------------------------------------------------------- action tools


def test_apply_cleaning_writes_a_cleaned_copy_when_permitted(action_ctx):
    outcome = execute_tool(action_ctx, "apply_cleaning", {})

    assert outcome.status == STATUS_OK
    assert outcome.value["applied"] is True
    assert action_ctx.dataset.cleaned_path is not None
    # Commit 1's extraction means the audit log is recorded here too.
    assert action_ctx.dataset.cleaning_log


def test_apply_cleaning_invalidates_the_cached_frame(action_ctx):
    """A later tool in the same run must see what cleaning produced, not the
    copy that was cached before it ran."""
    before = execute_tool(action_ctx, "get_dataset_overview", {})
    assert before.value["profile"]["rows"] == 8

    execute_tool(action_ctx, "apply_cleaning", {})

    assert action_ctx._frames == {}, "frames must be dropped after an action"
    after = execute_tool(action_ctx, "get_dataset_overview", {})
    assert after.status == STATUS_OK


def test_train_model_respects_the_hourly_training_limit(action_ctx, monkeypatch):
    monkeypatch.setattr(settings, "MAX_TRAINING_JOBS_PER_HOUR", 0)
    outcome = execute_tool(action_ctx, "train_model", {"target_column": "revenue"})

    assert outcome.status == STATUS_TOOL_ERROR
    assert outcome.error_code == "training_rate_limited"


def test_train_model_validates_its_task_type(action_ctx):
    outcome = execute_tool(action_ctx, "train_model", {"task_type": "clustering"})

    assert outcome.status == STATUS_INVALID_ARGUMENTS
    assert "task_type" in outcome.error


# ------------------------------------------------------------ error shaping


def test_errors_are_handed_to_the_model_as_data(ctx):
    outcome = execute_tool(ctx, "profile_column", {"column": "nope"})
    payload = outcome.for_model()

    assert payload["error_code"] == "unknown_column"
    assert payload["error"]


def test_the_valid_column_names_reach_the_model_when_it_guesses_wrong(ctx):
    """The handler attached the valid names to the error, but `for_model` once
    dropped them, so the model was told the column was missing and not what exists.
    The existing check only looked at `outcome.value`, which the model never sees."""
    outcome = execute_tool(ctx, "profile_column", {"column": "REVENUE"})
    payload = outcome.for_model()

    assert payload["error_code"] == "unknown_column"
    assert "revenue" in payload["valid_columns"] and payload["column_count"] == 6


def test_failures_without_extra_detail_are_shaped_as_before(ctx):
    payload = execute_tool(
        ctx, "get_dataset_overview", ["not", "an", "object"]
    ).for_model()
    assert set(payload) == {"error", "error_code"}


def test_the_exact_match_gate_is_unchanged_by_column_discovery(ctx):
    """Showing the model the valid names must not make the tool forgiving: a
    wrongly cased name is still refused, not silently corrected."""
    for wrong in ("REVENUE", "Revenue", "revenu", " revenue"):
        outcome = execute_tool(ctx, "profile_column", {"column": wrong})
        assert (
            outcome.status == STATUS_TOOL_ERROR
            and outcome.error_code == "unknown_column"
        )
    assert (
        execute_tool(ctx, "profile_column", {"column": "revenue"}).status == STATUS_OK
    )


def test_list_columns_returns_the_actual_names_and_coarse_types_in_order(ctx):
    outcome = execute_tool(ctx, "list_columns", {})

    assert outcome.status == STATUS_OK
    names = [c["name"] for c in outcome.value["columns"]]
    assert names == ["date", "region", "product", "units", "price", "revenue"]
    assert outcome.value["column_count"] == 6
    kinds = {c["name"]: c["type"] for c in outcome.value["columns"]}
    assert kinds["units"] == "number" and kinds["region"] == "text"
    assert kinds["revenue"] == "number"


def test_list_columns_takes_no_arguments_and_is_read_only(ctx):
    assert next(t for t in TOOLS if t.name == "list_columns").read_only is True
    assert (
        execute_tool(ctx, "list_columns", {"dataset_id": 2}).status
        == STATUS_INVALID_ARGUMENTS
    )


def test_a_handler_crash_becomes_an_outcome_not_an_exception(ctx, monkeypatch):
    """One broken tool must not end the run.

    The failure is injected into the service the handler calls, rather than into
    the registry, so this exercises the real path an unexpected library error
    would take.
    """
    import app.services.tool_registry as registry

    def boom(*_args, **_kwargs):
        raise RuntimeError("something internal broke")

    monkeypatch.setattr(registry, "compute_correlations", boom)
    outcome = execute_tool(ctx, "get_correlations", {})

    assert outcome.status == STATUS_TOOL_ERROR
    assert outcome.error_code == "tool_failed"
    # The internal message is logged, not handed to the model.
    assert "something internal broke" not in outcome.error
