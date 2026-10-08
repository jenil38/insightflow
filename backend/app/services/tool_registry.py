"""
The tools the LLM agent can call.

One definition per tool, in one place, because Phase 2 exposes the same tools
over MCP: the agent loop and the MCP server both read this registry rather than
each describing the tools their own way and drifting apart.

Three properties are structural here rather than left to the caller:

1. **Dataset scoping.** No tool takes a dataset id. Every tool receives a
   `ToolContext` holding the `Dataset` that `deps.get_owned_dataset` already
   resolved and authorised, so the model has no way to name another user's data.
2. **Argument validation.** Each tool declares a Pydantic model with
   `extra="forbid"`, so a hallucinated field is rejected rather than silently
   ignored, and a wrong type is reported back to the model as a result it can
   correct from.
3. **Failures are data.** `execute_tool` never raises. An unknown column, an
   invalid chart combination or a rate limit comes back as a `ToolOutcome` with
   a status and a message, because the agent loop has to be able to continue and
   the step has to be recordable in `agent_steps`.

Every handler wraps an existing service function. Nothing here reimplements
analysis logic; where a service already refuses something with a reason (see
`AnalyticsService._validate`), that reason is passed through unchanged.

Import cost: `MLService` and `ExplainabilityService` pull in scikit-learn, which
is about half the API's import time, so they are imported inside the two
handlers that need them. This mirrors what `app/ml.py`, `agent.py`, `explain.py`
and `report.py` do, and keeps a freshly woken instance able to answer sign-in
and /health without loading a library those paths never touch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from .. import models
from ..core.config import settings
from ..core.exceptions import AppException
from ..core.limits import check_training_rate
from ..core.logging_config import get_logger
from ..schemas import Aggregation, AnalyticsQuery, ChartType, CleaningConfig, TimeGrain
from .analytics_service import analytics_service
from .cleaning_service import cleaning_service
from .dataframe_io import load_dataset
from .profiling_service import (
    compute_correlations,
    compute_quality_scores,
    profile_column,
    profile_dataframe,
    profiling_service,
)

logger = get_logger("insightflow.agent.tools")

# How many valid column names to list back when the model names one that does
# not exist. Enough to correct itself, not enough to fill the step budget on a
# wide dataset.
MAX_COLUMNS_IN_ERROR = 60

# Explanations are ranked, so the tail carries little signal and a lot of text.
MAX_FEATURES_EXPLAINED = 15

# Status values, matching the `agent_steps.status` column.
STATUS_OK = "ok"
STATUS_INVALID_ARGUMENTS = "invalid_arguments"
STATUS_TOOL_ERROR = "tool_error"
STATUS_BLOCKED_ACTION = "blocked_action"
STATUS_UNKNOWN_TOOL = "rejected_unknown_tool"


# ---------------------------------------------------------------------------
# Context and outcome
# ---------------------------------------------------------------------------
@dataclass
class ToolContext:
    """What every tool is allowed to touch.

    The frame cache matters for more than speed: without it each tool call
    re-reads the file from disk, so a six-step run on a large upload would pay
    the read six times. It is keyed by `prefer` because the cleaning plan reads
    the original upload while analysis reads the cleaned copy when one exists.
    """

    db: Session
    dataset: models.Dataset
    user_id: int
    allow_actions: bool = False
    _frames: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)

    def frame(self, prefer: str = "auto") -> pd.DataFrame:
        if prefer not in self._frames:
            loaded = load_dataset(
                self.dataset, prefer=prefer, max_rows=settings.PROFILE_SAMPLE_ROWS
            )
            self._frames[prefer] = loaded.df
        return self._frames[prefer]

    def invalidate_frames(self) -> None:
        """Called after a tool changes the data on disk, so later tools in the
        same run read what the action actually produced rather than a stale
        copy."""
        self._frames.clear()


@dataclass
class ToolOutcome:
    status: str
    value: Any = None
    error: str | None = None
    error_code: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def for_model(self) -> Any:
        """What the model sees. An error is handed back as a plain object so it
        reads as a result to act on, not as a crash."""
        if self.ok:
            return self.value
        return {"error": self.error, "error_code": self.error_code}


# ---------------------------------------------------------------------------
# Argument models
# ---------------------------------------------------------------------------
class _Args(BaseModel):
    """Base for every tool's arguments.

    `extra="forbid"` is the point: a model that invents `dataset_id` or
    `use_cleaned` is told so, instead of having the field quietly dropped and
    getting a result that answers a different question.
    """

    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class ProfileColumnArgs(_Args):
    column: str = Field(
        min_length=1, description="Exact name of the column to profile."
    )


class RunQueryArgs(_Args):
    measure: str | None = Field(
        default=None,
        description="Numeric column to aggregate. Omit for count-only queries.",
    )
    aggregation: Aggregation = Field(
        default="sum", description="How to aggregate the measure."
    )
    dimension: str | None = Field(
        default=None,
        description="Column to group by, for example a region or category.",
    )
    date_column: str | None = Field(
        default=None, description="Date column to plot the measure over time."
    )
    time_grain: TimeGrain = Field(
        default="month", description="Bucket size when a date_column is given."
    )
    top_n: int = Field(
        default=10, ge=1, le=100, description="How many groups or buckets to return."
    )
    chart_type: ChartType = Field(
        default="bar",
        description=(
            "Shape of the answer. 'kpi' for a single number, 'histogram' for a "
            "distribution, 'scatter' for two measures, 'line' or 'area' over a "
            "date column, 'bar' or 'table' for grouped values."
        ),
    )
    secondary_measure: str | None = Field(
        default=None, description="Second numeric column, required by scatter."
    )


class TrainModelArgs(_Args):
    target_column: str | None = Field(
        default=None,
        description="Column to predict. Omit to let InsightFlow choose one.",
    )
    task_type: Literal["auto", "classification", "regression"] = Field(
        default="auto", description="Leave as 'auto' unless the user asked for one."
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def _dataset_overview(ctx: ToolContext, _args: NoArgs) -> Any:
    df = ctx.frame()
    return {
        "profile": profile_dataframe(df, ctx.dataset.size_bytes or 0),
        "quality": compute_quality_scores(df),
    }


def _profile_column(ctx: ToolContext, args: ProfileColumnArgs) -> Any:
    df = ctx.frame()
    if args.column not in df.columns:
        # Returned, not raised: the model can only recover if it is told which
        # names exist.
        columns = [str(c) for c in df.columns]
        raise _ToolError(
            f"Column '{args.column}' is not in this dataset.",
            error_code="unknown_column",
            extra={
                "valid_columns": columns[:MAX_COLUMNS_IN_ERROR],
                "column_count": len(columns),
            },
        )
    return profile_column(df, args.column)


def _correlations(ctx: ToolContext, _args: NoArgs) -> Any:
    correlations = compute_correlations(ctx.frame())
    return {
        "top_pairs": correlations.get("top_pairs", []),
        "note": "Pearson correlation. Association only, never causation.",
    }


def _assess_quality(ctx: ToolContext, _args: NoArgs) -> Any:
    df = ctx.frame()
    full = profiling_service.full_profile(df, ctx.dataset.size_bytes or 0)
    # full_profile returns twelve sections and is easily tens of kilobytes on a
    # wide dataset; only these three answer "what is wrong with my data".
    return {
        "quality": full["quality"],
        "warnings": full["warnings"],
        "recommendations": full["recommendations"],
    }


def _run_query(ctx: ToolContext, args: RunQueryArgs) -> Any:
    query = AnalyticsQuery(**args.model_dump())
    # AnalyticsService._validate refuses combinations that would mislead (a sum
    # over a text column, a pie chart over forty categories) with a specific
    # error_code. Those propagate as AppException and are passed to the model
    # unchanged - they are better feedback than anything written here.
    return analytics_service.run_query(ctx.frame(), query)


def _recommend_cleaning(ctx: ToolContext, _args: NoArgs) -> Any:
    return cleaning_service.recommend_config(ctx.frame(prefer="original"))


def _model_results(ctx: ToolContext, _args: NoArgs) -> Any:
    from .ml_service import MLService

    runs = MLService(ctx.db).history(ctx.dataset.id, ctx.user_id)
    if not runs:
        return {
            "trained": False,
            "detail": (
                "No model has been trained for this dataset yet. Use train_model "
                "if training is permitted, or say that training is needed."
            ),
        }
    return {"trained": True, "latest": runs[0], "earlier_versions": runs[1:4]}


def _explain_model(ctx: ToolContext, _args: NoArgs) -> Any:
    from .explainability_service import ExplainabilityService

    explanation = ExplainabilityService(ctx.db).explain(ctx.dataset, ctx.user_id)
    importance = explanation.get("feature_importance") or []
    return {
        **explanation,
        "feature_importance": importance[:MAX_FEATURES_EXPLAINED],
        "features_shown": min(len(importance), MAX_FEATURES_EXPLAINED),
        "features_total": len(importance),
    }


def _apply_cleaning(ctx: ToolContext, _args: NoArgs) -> Any:
    plan = cleaning_service.recommend_config(ctx.frame(prefer="original"))
    config = CleaningConfig(**plan["recommended_config"])
    _cleaned, report = cleaning_service.apply_and_persist(ctx.db, ctx.dataset, config)
    # The cleaned copy is now what analysis reads, so any frame cached earlier
    # in this run is stale.
    ctx.invalidate_frames()
    return {
        "applied": True,
        "before": report.get("before"),
        "after": report.get("after"),
        "steps": report.get("steps"),
        "reversible": "The original upload is kept and this can be reverted.",
    }


def _train_model(ctx: ToolContext, args: TrainModelArgs) -> Any:
    from ..schemas import TrainRequest
    from .ml_service import MLService

    # Training is the most expensive thing the agent can do, so it is metered
    # with the same hourly limit the /train route uses.
    check_training_rate(ctx.db, ctx.user_id)

    request = TrainRequest(target_column=args.target_column, task_type=args.task_type)
    result = MLService(ctx.db).train(ctx.dataset, ctx.user_id, request)
    return {
        "task_type": result.get("task_type"),
        "target_column": result.get("target_column"),
        "best_model": result.get("best_model"),
        "rows_used": result.get("rows_used"),
        "results": result.get("results"),
        "warnings": result.get("warnings"),
        "model_version": result.get("model_version"),
    }


class _ToolError(Exception):
    """Raised inside a handler to produce a `tool_error` outcome with extra
    detail attached. Kept private: outside this module a tool failure is a
    `ToolOutcome`, never an exception."""

    def __init__(
        self, message: str, error_code: str, extra: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.extra = extra or {}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], Any]
    read_only: bool

    def json_schema(self) -> dict[str, Any]:
        """OpenAI-style function schema, which is also what MCP needs."""
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="get_dataset_overview",
        description=(
            "Get the size, shape and overall data-quality scores of this dataset. "
            "Call this first if you do not yet know what the dataset contains."
        ),
        args_model=NoArgs,
        handler=_dataset_overview,
        read_only=True,
    ),
    Tool(
        name="profile_column",
        description=(
            "Get detailed statistics for one named column: type, missing values, "
            "distinct values, min, max, mean, median, outlier count and the most "
            "common values."
        ),
        args_model=ProfileColumnArgs,
        handler=_profile_column,
        read_only=True,
    ),
    Tool(
        name="get_correlations",
        description=(
            "Find the strongest linear relationships between the numeric columns."
        ),
        args_model=NoArgs,
        handler=_correlations,
        read_only=True,
    ),
    Tool(
        name="assess_quality",
        description=(
            "Get the data-quality warnings and the recommended fixes for this "
            "dataset, with the score each one is based on."
        ),
        args_model=NoArgs,
        handler=_assess_quality,
        read_only=True,
    ),
    Tool(
        name="run_query",
        description=(
            "Aggregate the data to answer a quantitative question: totals or "
            "averages by category, a measure over time, a distribution, or a "
            "single figure."
        ),
        args_model=RunQueryArgs,
        handler=_run_query,
        read_only=True,
    ),
    Tool(
        name="recommend_cleaning",
        description=(
            "See what cleaning this dataset needs and why. This only inspects the "
            "data and changes nothing."
        ),
        args_model=NoArgs,
        handler=_recommend_cleaning,
        read_only=True,
    ),
    Tool(
        name="get_model_results",
        description=(
            "Get the results of the most recent model training run for this "
            "dataset, including the best model and its scores."
        ),
        args_model=NoArgs,
        handler=_model_results,
        read_only=True,
    ),
    Tool(
        name="explain_model",
        description=(
            "Explain which columns most influence the trained model's predictions."
        ),
        args_model=NoArgs,
        handler=_explain_model,
        read_only=True,
    ),
    Tool(
        name="apply_cleaning",
        description=(
            "Apply the recommended cleaning to this dataset, writing a cleaned "
            "copy. The original upload is kept and this can be reverted."
        ),
        args_model=NoArgs,
        handler=_apply_cleaning,
        read_only=False,
    ),
    Tool(
        name="train_model",
        description=(
            "Train and compare models to predict a target column, and return the "
            "leaderboard. This takes a while and records a new model version."
        ),
        args_model=TrainModelArgs,
        handler=_train_model,
        read_only=False,
    ),
)

_BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def tools_for(allow_actions: bool) -> tuple[Tool, ...]:
    """The tools available for a request.

    When actions are not permitted the two action tools are left out entirely
    rather than offered and then refused: a tool the model cannot use should not
    be in its list, because advertising it invites a wasted step.
    """
    if allow_actions:
        return TOOLS
    return tuple(tool for tool in TOOLS if tool.read_only)


def tools_schema(allow_actions: bool) -> list[dict[str, Any]]:
    return [tool.json_schema() for tool in tools_for(allow_actions)]


def get_tool(name: str) -> Tool | None:
    return _BY_NAME.get(name)


def execute_tool(ctx: ToolContext, name: str, arguments: Any) -> ToolOutcome:
    """Validate and run one tool call. Never raises.

    Everything the model can get wrong - an unknown tool, a malformed argument
    object, a column that does not exist, an action it is not allowed to take -
    comes back as an outcome the loop can record and feed back.
    """
    tool = _BY_NAME.get(name)
    if tool is None:
        return ToolOutcome(
            status=STATUS_UNKNOWN_TOOL,
            error=(
                f"There is no tool called '{name}'. Available tools: "
                + ", ".join(t.name for t in tools_for(ctx.allow_actions))
            ),
            error_code="unknown_tool",
        )

    if not tool.read_only and not ctx.allow_actions:
        return ToolOutcome(
            status=STATUS_BLOCKED_ACTION,
            error=(
                f"'{name}' changes the dataset and this request did not permit "
                "actions. Answer using the read-only tools, and say that this "
                "step needs to be approved."
            ),
            error_code="action_not_permitted",
        )

    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return ToolOutcome(
            status=STATUS_INVALID_ARGUMENTS,
            error=(
                f"Arguments for '{name}' must be a JSON object, got "
                f"{type(arguments).__name__}."
            ),
            error_code="arguments_not_an_object",
        )

    try:
        args = tool.args_model(**arguments)
    except ValidationError as exc:
        return ToolOutcome(
            status=STATUS_INVALID_ARGUMENTS,
            error=f"Invalid arguments for '{name}': {_describe_validation(exc)}",
            error_code="invalid_arguments",
        )

    try:
        return ToolOutcome(status=STATUS_OK, value=tool.handler(ctx, args))
    except _ToolError as exc:
        return ToolOutcome(
            status=STATUS_TOOL_ERROR,
            value=exc.extra or None,
            error=exc.message,
            error_code=exc.error_code,
        )
    except AppException as exc:
        # Services already refuse bad requests with a usable reason and code
        # (unknown_column, measure_not_numeric, no_trained_model, a rate limit),
        # so pass those through rather than restating them.
        return ToolOutcome(
            status=STATUS_TOOL_ERROR,
            error=exc.detail,
            error_code=getattr(exc, "error_code", None),
        )
    except Exception as exc:  # noqa: BLE001
        # Deliberately broad: one failing tool must not end the run, and the
        # model needs to be told something it can act on. The detail is logged
        # rather than returned, since an internal traceback is not useful to the
        # model and may quote data.
        logger.exception("Tool %s failed unexpectedly", name)
        return ToolOutcome(
            status=STATUS_TOOL_ERROR,
            error=f"'{name}' failed unexpectedly ({type(exc).__name__}).",
            error_code="tool_failed",
        )


def _describe_validation(exc: ValidationError) -> str:
    """Flatten Pydantic's errors into one line the model can act on."""
    parts = []
    for error in exc.errors()[:5]:
        location = ".".join(str(piece) for piece in error.get("loc", ())) or "(root)"
        parts.append(f"{location}: {error.get('msg')}")
    return "; ".join(parts)
