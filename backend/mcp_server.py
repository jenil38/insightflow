"""MCP server exposing InsightFlow's agent tools to any MCP client.

Run with:

    python -m backend.mcp_server

See the README's "MCP server" section for a `claude_desktop_config.json`
example.

This is a thin adapter, not a second implementation. Every tool here calls
`app.services.tool_registry.execute_tool` - the same function the chat agent
(`ToolAgentService`) calls - so a tool's behaviour, argument validation and
error shape are defined exactly once, in `tool_registry.py`. Nothing in this
file re-implements analysis logic.

Authentication and scoping
---------------------------
This server runs locally, as the user's own process, reading their own
InsightFlow database (whatever `DATABASE_URL` the environment or `.env`
already configures - the same setting the FastAPI app uses). There is no
login flow: the user to act as is named once, by `INSIGHTFLOW_USER_ID`, an
environment variable set when the server is started. Every tool call then
resolves the requested dataset through `app.deps.get_owned_dataset`, the
exact function every REST route already uses, so a dataset id for someone
else's data is refused with the same "not found" (never "forbidden", which
would confirm the id exists) that the API gives.

The human-approval gate
------------------------
`apply_cleaning` and `train_model` change the dataset or spend a training
run, so the chat agent never executes either one on its own: it stops and
waits for the user to approve. This server holds to the same rule in a
stronger form - it has no notion of a later "approved" call at all, so it
never executes either tool, ever. Both return a `pending_confirmation`
payload describing what calling them for real would do (the same sentence
`describe_proposal` writes for the chat agent's approval card), and nothing
on the dataset changes. To actually run one, use InsightFlow's agent chat
(which asks for approval) or the dedicated REST endpoint.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app import deps  # noqa: E402
from app.core.exceptions import AppException  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402
from app.schemas import Aggregation, ChartType, TimeGrain  # noqa: E402
from app.services.tool_agent_service import describe_proposal  # noqa: E402
from app.services.tool_registry import (  # noqa: E402
    ToolContext,
    _describe_validation,
    execute_tool,
    get_tool,
)

mcp = MCPServer("insightflow_mcp")

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
ACTION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)


def _error(message: str, error_code: str) -> dict[str, Any]:
    return {"error": message, "error_code": error_code}


def _dispatch(
    tool_name: str, dataset_id: int, arguments: dict[str, Any], *, action: bool
) -> dict[str, Any]:
    """Resolve the user and their owned dataset, then either run a read-only
    tool for real or build a pending-action payload for an action tool -
    never both for the same call."""
    raw_user_id = os.environ.get("INSIGHTFLOW_USER_ID")
    if not raw_user_id:
        return _error(
            "INSIGHTFLOW_USER_ID is not set. Set it to your InsightFlow user id "
            "before starting this server.",
            "missing_user_id",
        )
    try:
        user_id = int(raw_user_id)
    except ValueError:
        return _error(
            f"INSIGHTFLOW_USER_ID must be an integer, got {raw_user_id!r}.",
            "invalid_user_id",
        )

    db = SessionLocal()
    try:
        user = UserRepository(db).get(user_id)
        if user is None:
            return _error(f"No user with id {user_id}.", "user_not_found")

        try:
            dataset = deps.get_owned_dataset(
                dataset_id=dataset_id, db=db, current_user=user
            )
        except AppException as exc:
            # The same refusal `get_owned_dataset` gives the REST API for a
            # dataset id that does not exist or belongs to someone else.
            return _error(exc.detail, exc.error_code)

        if action:
            tool = get_tool(tool_name)
            if tool is None or tool.read_only:
                return _error(
                    f"'{tool_name}' is not an action tool.", "not_an_action_tool"
                )
            try:
                tool.args_model(**arguments)
            except ValidationError as exc:
                return _error(
                    f"Invalid arguments for '{tool_name}': {_describe_validation(exc)}",
                    "invalid_arguments",
                )
            return {
                "status": "pending_confirmation",
                "tool_name": tool_name,
                "dataset_id": dataset.id,
                "arguments": arguments,
                "description": describe_proposal(tool_name, arguments),
                "note": (
                    "This MCP server never runs apply_cleaning or train_model "
                    "directly, and nothing has been changed. To actually run "
                    "this, approve it in InsightFlow's agent chat or use the "
                    "dataset's cleaning/training endpoint."
                ),
            }

        ctx = ToolContext(db=db, dataset=dataset, user_id=user.id, allow_actions=False)
        return execute_tool(ctx, tool_name, arguments).for_model()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Read-only tools (11)
# ---------------------------------------------------------------------------


@mcp.tool(name="get_dataset_overview", annotations=READ_ONLY)
def get_dataset_overview(dataset_id: int) -> dict[str, Any]:
    """Get the size, shape and overall data-quality scores of a dataset you
    own. Call this first if you do not yet know what the dataset contains."""
    return _dispatch("get_dataset_overview", dataset_id, {}, action=False)


@mcp.tool(name="list_columns", annotations=READ_ONLY)
def list_columns(dataset_id: int) -> dict[str, Any]:
    """List a dataset's actual column names and their types (number, text,
    date, true/false). Column names are case-sensitive and must be used
    exactly as listed."""
    return _dispatch("list_columns", dataset_id, {}, action=False)


@mcp.tool(name="profile_column", annotations=READ_ONLY)
def profile_column(dataset_id: int, column: str) -> dict[str, Any]:
    """Get detailed statistics for one named column: type, missing values,
    distinct values, min, max, mean, median, outlier count and the most
    common values."""
    return _dispatch("profile_column", dataset_id, {"column": column}, action=False)


@mcp.tool(name="get_correlations", annotations=READ_ONLY)
def get_correlations(dataset_id: int) -> dict[str, Any]:
    """Find the strongest linear relationships between a dataset's numeric
    columns."""
    return _dispatch("get_correlations", dataset_id, {}, action=False)


@mcp.tool(name="assess_quality", annotations=READ_ONLY)
def assess_quality(dataset_id: int) -> dict[str, Any]:
    """Get the data-quality warnings and the recommended fixes for a
    dataset, with the score each one is based on."""
    return _dispatch("assess_quality", dataset_id, {}, action=False)


@mcp.tool(name="run_query", annotations=READ_ONLY)
def run_query(
    dataset_id: int,
    measure: str | None = None,
    aggregation: Aggregation = "sum",
    dimension: str | None = None,
    date_column: str | None = None,
    time_grain: TimeGrain = "month",
    top_n: int = 10,
    chart_type: ChartType = "bar",
    secondary_measure: str | None = None,
) -> dict[str, Any]:
    """Aggregate a dataset to answer a quantitative question: totals or
    averages by category, a measure over time, a distribution, or a single
    figure."""
    arguments = {
        "measure": measure,
        "aggregation": aggregation,
        "dimension": dimension,
        "date_column": date_column,
        "time_grain": time_grain,
        "top_n": top_n,
        "chart_type": chart_type,
        "secondary_measure": secondary_measure,
    }
    return _dispatch("run_query", dataset_id, arguments, action=False)


@mcp.tool(name="recommend_cleaning", annotations=READ_ONLY)
def recommend_cleaning(dataset_id: int) -> dict[str, Any]:
    """See what cleaning a dataset needs and why. This only inspects the
    data and changes nothing."""
    return _dispatch("recommend_cleaning", dataset_id, {}, action=False)


@mcp.tool(name="recommend_targets", annotations=READ_ONLY)
def recommend_targets(dataset_id: int, limit: int = 3) -> dict[str, Any]:
    """Rank which columns would make sensible prediction targets, with the
    reasoning behind each one."""
    return _dispatch("recommend_targets", dataset_id, {"limit": limit}, action=False)


@mcp.tool(name="auto_dashboard", annotations=READ_ONLY)
def auto_dashboard(dataset_id: int) -> dict[str, Any]:
    """Get the automatically chosen KPIs, time series, category breakdown
    and histogram for a dataset - the same view the dashboard page shows."""
    return _dispatch("auto_dashboard", dataset_id, {}, action=False)


@mcp.tool(name="get_model_results", annotations=READ_ONLY)
def get_model_results(dataset_id: int) -> dict[str, Any]:
    """Get the results of the most recent model training run for a dataset,
    including the best model and its scores."""
    return _dispatch("get_model_results", dataset_id, {}, action=False)


@mcp.tool(name="explain_model", annotations=READ_ONLY)
def explain_model(dataset_id: int) -> dict[str, Any]:
    """Explain which columns most influence the trained model's
    predictions."""
    return _dispatch("explain_model", dataset_id, {}, action=False)


# ---------------------------------------------------------------------------
# Action tools (2) - never executed; always return a pending-action payload.
# ---------------------------------------------------------------------------


@mcp.tool(name="apply_cleaning", annotations=ACTION)
def apply_cleaning(dataset_id: int) -> dict[str, Any]:
    """Describe applying the recommended cleaning to a dataset. This never
    runs the cleaning: it returns a pending-action payload so the change can
    be approved first, the same gate InsightFlow's agent chat uses."""
    return _dispatch("apply_cleaning", dataset_id, {}, action=True)


@mcp.tool(name="train_model", annotations=ACTION)
def train_model(
    dataset_id: int,
    target_column: str | None = None,
    task_type: Literal["auto", "classification", "regression"] = "auto",
) -> dict[str, Any]:
    """Describe training models to predict a target column. This never runs
    training: it returns a pending-action payload so the run can be approved
    first, the same gate InsightFlow's agent chat uses."""
    return _dispatch(
        "train_model",
        dataset_id,
        {"target_column": target_column, "task_type": task_type},
        action=True,
    )


if __name__ == "__main__":
    mcp.run()
