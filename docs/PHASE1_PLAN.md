# Phase 1 plan: LLM agent with tool calling

Status: **implemented and merged (PR #1).** The original plan text below is kept as
written. One behaviour has since changed: action tools (`apply_cleaning`,
`train_model`) no longer run inside `ask` even with `allow_actions=true`; they stop
the run for the user's approval. See `backend/PHASE1_1_PLAN.md`.

Source plan: `D:\Resumes\InsightFlow upgrade plan.md`, Phase 1.

This document is written incrementally, appending after each source file is read, so
every finding below is quoted from the real code rather than recalled. Signatures are
copied verbatim; where something does not line up with the intended design it is
recorded under "Mismatches" instead of being smoothed over.

## Target repository (confirmed)

Build in **`F:\InsightFlow - Publish\InsightFlow`**.

- `git remote -v` → `origin  https://github.com/jenil38/insightflow.git`
- Clean working tree, in sync with `origin/main` at `7dae1e7`.

Do **not** build in `F:\InsightFlow\InsightFlow`. It is not a git repository, and a
file-by-file comparison of `backend/app` showed it is the older copy: all 41 Python
files differ, almost entirely by formatting, and the newer work (lazy scikit-learn
imports for cold-start, em dash cleanup) exists only in the published repo.

## What this plan must not change

- `services/chat_service.py` - the existing Copilot behaviour.
- `services/agent_service.py` - the fixed 7-step Guided Analysis pipeline.

The new agent is added beside both.

---

## Code read so far

Every file below was read in this session, and the notes were appended immediately after
each one. Nothing here is recalled from memory.

| File | What it settled |
|---|---|
| `app/deps.py` | ownership dependency, 404-not-403 behaviour |
| `app/core/limits.py` | `check_copilot_rate`, `check_training_rate` signatures |
| `app/services/chat_service.py` | `LLMProvider`, `CircuitBreaker`, `_sanitize`, settings |
| `app/services/profiling_service.py` | 13 pure functions + `profiling_service` singleton |
| `app/services/analytics_service.py` | `run_query`, `_validate` refusal codes, singleton |
| `app/schemas.py` | `AnalyticsQuery`, `CleaningConfig`, `TrainRequest` + literals |
| `app/services/cleaning_service.py` | `recommend_config` / `apply_config` / `preview` |
| `app/cleaning.py` | where cleaned files are actually persisted |
| `app/services/agent_service.py` | the duplicated persistence precedent |
| `app/services/ml_service.py` | `MLService.train` / `latest_run` / `history` |
| `app/services/explainability_service.py` | `ExplainabilityService.explain` |
| `app/models.py` | column/relationship/index conventions |
| `alembic/versions/*` | migration chain and current head |
| `app/agent.py` | the route pattern to sit beside |
| `tests/conftest.py` | fixtures, autouse table creation, missing `GROQ_API_KEY` |
| `app/core/config.py` | `copilot_enabled`, `GROQ_*`, sampling caps |
| `.github/workflows/ci.yml` | ruff flags, pytest flags, migration job |

### `app/deps.py`

```python
def get_owned_dataset(
    dataset_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
) -> models.Dataset:
```

Returns the `models.Dataset` the authenticated user owns, raising
`NotFoundError("Dataset not found", error_code="dataset_not_found")` (404, deliberately
not 403) when it is missing or owned by someone else.

Consequence for the agent: the route depends on this, and the resolved `Dataset` object
is passed into the tool layer. No tool takes a dataset id as an argument, so the model
has no way to address another user's data.

### `app/core/limits.py`

Both required limiters exist and share one shape: count rows in a window, raise
`RateLimitedError` past the cap.

```python
def check_training_rate(db: Session, user_id: int) -> None   # counts models.ModelRun in last 1h
                                                             # cap settings.MAX_TRAINING_JOBS_PER_HOUR
                                                             # error_code="training_rate_limited"

def check_copilot_rate(db: Session, user_id: int) -> None    # counts models.ChatMessage (role=="user")
                                                             # in last 1h
                                                             # cap settings.MAX_COPILOT_MESSAGES_PER_HOUR
                                                             # error_code="copilot_rate_limited"
```

Note for the agent loop: `check_copilot_rate` counts rows in `ChatMessage` where
`role == "user"`. The new agent does not write to `ChatMessage` (it writes to
`agent_runs` / `agent_steps`), so calling `check_copilot_rate` will throttle agent
requests against the user's *Copilot* history without adding to it. That is a real
design question, recorded under "Open questions".

### `app/services/chat_service.py`

The file the new agent must extend **without changing**. Everything reusable, verbatim:

```python
class LLMProvider:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int)
    def chat(self, messages: list[dict[str, str]]) -> str      # line 61

class CircuitBreaker:
    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"
    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 60.0)
    @property
    def state(self) -> str
    def record_success(self) -> None
    def record_failure(self) -> None
    def check(self) -> None            # raises copilot_circuit_open, 503

def _build_provider() -> LLMProvider   # line 158, module level
_circuit = CircuitBreaker()            # line 167, module-level singleton

SYSTEM_PROMPT       # line 169
INJECTION_PATTERNS  # line 183, compiled regex
MAX_CELL_LENGTH = 120  # line 190

class ChatService:
    @staticmethod
    def _sanitize(text: str) -> str                          # line 437
    @classmethod
    def _sanitize_cell(cls, value: Any) -> tuple[str, bool]  # line 451
    def _call_llm(self, messages: list[dict[str, str]]) -> str  # line 312
```

`LLMProvider.chat` posts to `{base_url}/chat/completions` with `temperature=0.2`,
`max_tokens=800`, and maps provider failures onto `copilot_bad_key` (401),
`copilot_rate_limited` (429), `copilot_provider_error` (>=400) and
`copilot_bad_response` (unparseable body).

`_sanitize` and `_sanitize_cell` are a `@staticmethod` and a `@classmethod`, so the new
service can call them without constructing a `ChatService`. Good news for reuse.

Settings consumed (from `app/core/config.py`): `GROQ_API_KEY`, `GROQ_MODEL`,
`GROQ_TIMEOUT_SECONDS`, `copilot_enabled`, `PROFILE_SAMPLE_ROWS`,
`COPILOT_HISTORY_TURNS`, `COPILOT_SAMPLE_ROWS`.

**Two problems found here, both real:**

1. `chat()` returns `response.json()["choices"][0]["message"]["content"].strip()` - a
   bare `str`. It throws away `tool_calls` and the `usage` block. Since the plan wants
   token usage recorded per step in `agent_steps`, `chat_with_tools` cannot be a thin
   wrapper over `chat()`; it has to read the raw message object and the usage counts
   itself. It will be added as a **new, separate method** so `chat()` and therefore the
   Copilot stay byte-for-byte unchanged.
2. `_sanitize` ends with `return cleaned[:MAX_CELL_LENGTH]`, i.e. a hard 120-character
   truncation. That is correct for a column name or one cell, but applying it to a whole
   tool result (a JSON blob of statistics) would shred it. See "Mismatches".

### `app/services/profiling_service.py`

Module-level functions (all pure, all take a `DataFrame` - no db, no `Dataset`):

```python
def infer_semantic_type(series: pd.Series) -> str                               # 102
def detect_datetime_columns(df: pd.DataFrame) -> list[str]                      # 142
def detect_numeric_columns(df: pd.DataFrame) -> list[str]                       # 146
def detect_categorical_columns(df: pd.DataFrame) -> list[str]                   # 150
def infer_task_type(series, semantic: str, distinct: int) -> str                # 154
def recommend_targets(df: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]] # 214
def profile_column(df: pd.DataFrame, column: str,
                   histogram_bins: int = 12) -> dict[str, Any]                  # 315
def compute_quality_scores(df: pd.DataFrame) -> dict[str, Any]                  # 499
def grade_for(score: float) -> str                                              # 523
def compute_correlations(df: pd.DataFrame,
                         max_columns: int | None = None) -> dict[str, Any]      # 538
def build_warnings(df, column_profiles: list[dict], scores: dict) -> list[dict] # 590
def build_recommendations(warnings_list: list[dict],
                          scores: dict) -> list[dict[str, Any]]                 # 713
def profile_dataframe(df: pd.DataFrame, size_bytes: int) -> dict[str, Any]      # 793
```

Class and singleton:

```python
class ProfilingService:                                                          # 839
    def full_profile(self, df, size_bytes: int, source: str = "original",
                     sampled: bool = False,
                     total_rows: int | None = None) -> dict[str, Any]            # 843
    def column_profile(self, df, column: str) -> dict[str, Any]                  # 941
    def columns_overview(self, df) -> list[dict[str, Any]]                       # 944

profiling_service = ProfilingService()                                           # 968
```

Return shapes that matter for tool design:

- `compute_quality_scores` → `overall_score`, `completeness_score`,
  `duplicate_score`, `consistency_score`, `uniqueness_score` (+ duplicate row count).
- `compute_correlations` → dict containing `top_pairs`, each `{x, y, correlation}`.
- `full_profile` → twelve top-level keys: `summary`, `quality`,
  `column_type_distribution`, `missing_by_column`, `outliers_by_column`,
  `numeric_summary`, `categorical_summary`, `correlations`, `target_candidates`,
  `warnings`, `recommendations`, `data_dictionary`.

**Two notes carried into tool design:**

1. `full_profile` returns a very large object - on a wide dataset it is easily tens of
   kilobytes. Feeding it back to the model whole would burn the step budget in one call.
   The `assess_quality` tool must therefore return only the `quality`, `warnings` and
   `recommendations` slices, not the full payload.
2. `profile_column` starts with `series = df[column]`, so an unknown column raises
   `KeyError`. This is exactly the case the owner requires to come back as an error
   *result* rather than an exception, so the tool wrapper must catch it and return the
   valid column list alongside the error.

### `app/services/analytics_service.py` + `AnalyticsQuery`

```python
class AnalyticsService:                                                          # 39
    def auto_dashboard(self, df: pd.DataFrame) -> dict[str, Any]                 # 41
    def run_query(self, df: pd.DataFrame,
                  query: AnalyticsQuery) -> dict[str, Any]                       # 113
    def _validate(self, df: pd.DataFrame, query: AnalyticsQuery) -> None         # 127

analytics_service = AnalyticsService()                                           # 405
```

The query object, verbatim from `app/schemas.py:229`:

```python
Aggregation = Literal["sum", "avg", "count", "min", "max", "median"]   # 214
TimeGrain   = Literal["day", "week", "month", "quarter", "year"]       # 215
ChartType   = Literal["line", "area", "bar", "horizontal_bar", "pie",
                      "scatter", "histogram", "table", "kpi"]          # 216

class AnalyticsQuery(BaseModel):                                       # 229
    measure: str | None = None
    aggregation: Aggregation = "sum"
    dimension: str | None = None
    date_column: str | None = None
    time_grain: TimeGrain = "month"
    top_n: int = Field(default=10, ge=1, le=100)
    chart_type: ChartType = "bar"
    secondary_measure: str | None = None
    use_cleaned: bool = True
```

Branch selection in `run_query` (line 117-125): `kpi` → `_kpi`, `histogram` →
`_histogram`, `scatter` → `_scatter`, `line`/`area` **or any `date_column`** →
`_timeseries_result`, otherwise `_grouped`.

`_validate` already refuses statistically invalid combinations with a stated reason.
These become high-quality tool error results, reusable as-is:

| `error_code` | Refuses |
|---|---|
| `unknown_column` | any of measure / dimension / date_column / secondary_measure not in the frame |
| `measure_required` | a non-`count` aggregation with no measure; also histogram with no measure |
| `measure_not_numeric` | aggregating a text column |
| `date_column_required` | `line`/`area` with no date column |
| `two_measures_required` | `scatter` without both measures |
| `too_many_slices` | `pie` over more than `MAX_PIE_SLICES` distinct values |

All are `ValidationAppError`, which subclasses `AppException`. The tool wrapper catches
`AppException` and returns `{"error": ..., "error_code": ...}` to the model, so a bad
query teaches the model to retry correctly instead of aborting the run.

### `app/services/cleaning_service.py` + `CleaningConfig`

```python
class CleaningService:                                                           # 23
    def recommend_config(self, df: pd.DataFrame) -> dict[str, Any]               # 25
    def apply_config(self, df: pd.DataFrame,
                     config: CleaningConfig) -> tuple[pd.DataFrame, dict]        # 81
    def preview(self, df: pd.DataFrame, config: CleaningConfig,
                sample_rows: int = 10) -> dict[str, Any]                         # 302

cleaning_service = CleaningService()                                             # 467
```

```python
NumericMissingStrategy     = Literal["median", "mean", "zero", "drop", "leave"]  # 180
CategoricalMissingStrategy = Literal["mode", "unknown", "drop", "leave"]         # 181
OutlierStrategy            = Literal["report", "cap", "remove", "leave"]         # 182
CaseStrategy               = Literal["none", "lower", "upper", "title"]          # 183

class CleaningConfig(BaseModel):                                                 # 186
    remove_duplicates: bool = True
    trim_whitespace: bool = True
    normalize_whitespace: bool = True
    standardize_case: CaseStrategy = "none"
    parse_dates: bool = True
    numeric_missing_strategy: NumericMissingStrategy = "median"
    categorical_missing_strategy: CategoricalMissingStrategy = "mode"
    outlier_strategy: OutlierStrategy = "report"
    drop_empty_columns: bool = False
```

`recommend_config` returns `{"recommended_config": {...}, "reasons": [...], ...}`;
`agent_service.py:116` consumes it as `CleaningConfig(**plan["recommended_config"])`.

**Important: `apply_config` persists nothing.** It is pure - it takes a frame and
returns `(cleaned_df, report)`. Writing the cleaned copy happens *outside* the service,
and currently in two places that do not agree:

`app/cleaning.py:64-74` (the route):

```python
cleaned_df, report = cleaning_service.apply_config(loaded.df, config)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
target_path = cleaned_path_for(dataset)
write_dataframe(cleaned_df, target_path)
dataset.cleaned_path = target_path
dataset.cleaning_log = report.get("steps", [])   # <-- sets the audit log
db.commit()
```

`app/services/agent_service.py:118-124` (Guided Analysis):

```python
cleaned_df, report = cleaning_service.apply_config(full.df, config)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
target = cleaned_path_for(dataset)
write_dataframe(cleaned_df, target)
dataset.cleaned_path = target
self.db.commit()                                  # <-- never sets cleaning_log
```

So the persistence sequence is already duplicated, and the Guided Analysis copy silently
leaves `dataset.cleaning_log` stale. See "Mismatches" - this is the one place where the
instruction "wrap an existing service function, do not duplicate logic" cannot be
satisfied as written, because no service function does the persisting.

---

### `app/services/ml_service.py` and `app/services/explainability_service.py`

```python
class MLService:                                                                 # 393
    def __init__(self, db: Session)                                              # 394
    def config_options(self, dataset: models.Dataset,
                       use_cleaned: bool = True) -> dict[str, Any]               # 398
    def train(self, dataset: models.Dataset, user_id: int,
              request: TrainRequest | None = None) -> dict[str, Any]             # 469
    def latest_run(self, dataset_id: int,
                   user_id: int) -> models.ModelRun | None                       # 938
    def history(self, dataset_id: int, user_id: int) -> list[dict[str, Any]]     # 951

class ExplainabilityService:                                                     # 51
    def __init__(self, db: Session)                                              # 52
    def explain(self, dataset: models.Dataset, user_id: int) -> dict[str, Any]   # 56
```

```python
class TrainRequest(BaseModel):                                                   # schemas.py:270
    target_column: str | None = None
    task_type: Literal["auto", "classification", "regression"] = "auto"
    excluded_columns: list[str] = Field(default_factory=list)
    test_size: float = Field(default=0.2, ge=0.05, le=0.5)
    cross_validation_folds: int = Field(default=5, ge=2, le=10)
    enable_tuning: bool = True
    use_cleaned: bool = True
```

- `latest_run` takes `dataset_id` (an int), **not** a `Dataset`, and returns an ORM
  `models.ModelRun` object. `history` takes the same arguments but returns an
  already-`to_jsonable` list.
- `explain` raises `NotFoundError(..., error_code="no_trained_model")` when no run
  exists - a clean, reusable error result.
- `train` is the expensive, state-mutating call: it writes `ModelRun` rows and a model
  file, and takes tens of seconds.
- Both services are constructed with a db session: `MLService(db)`,
  `ExplainabilityService(db)` (the latter builds its own `MLService` internally).
- `app/ml.py`, `agent.py`, `explain.py` and `report.py` import these **inside the
  function body**, not at module scope, to keep scikit-learn off the cold-start path.
  `tool_registry.py` must follow that pattern or it will undo the startup work.

---

## Tool list

Ten tools. Every one is scoped to the `Dataset` resolved by `get_owned_dataset`; none
takes a dataset id, so the model cannot address another user's data.

`df` below means the frame loaded by `load_dataset(dataset, ...)` inside the wrapper,
never an argument the model supplies.

### 1. `get_dataset_overview` - read_only

**Description shown to the model:** "Get the size, shape and overall data-quality scores
of this dataset. Call this first if you do not yet know what the dataset contains."

- **Arguments:** none
- **Wraps:** `app/services/profiling_service.py` → `profile_dataframe(df, size_bytes)`
  and `compute_quality_scores(df)`
- **Returns:** row/column counts, missing-value and duplicate percentages, and the four
  quality sub-scores (completeness, duplicates, consistency, uniqueness).

### 2. `profile_column` - read_only

**Description:** "Get detailed statistics for one named column: type, missing values,
distinct values, min/max/mean/median, outlier count, and most common values."

- **Arguments:** `column: str` (required)
- **Wraps:** `app/services/profiling_service.py` → `ProfilingService.column_profile(df,
  column)` (singleton `profiling_service`, which delegates to `profile_column`)
- **Note:** `profile_column` opens with `series = df[column]`, so an unknown name raises
  `KeyError`. The wrapper catches it and returns the list of valid columns as the error
  result, which is what lets the model correct itself.

### 3. `get_correlations` - read_only

**Description:** "Find the strongest linear relationships between the numeric columns."

- **Arguments:** none
- **Wraps:** `app/services/profiling_service.py` → `compute_correlations(df)`
- **Note:** return `top_pairs` only (`{x, y, correlation}`), never the full matrix -
  it is O(n²) in columns and capped at `MAX_CORRELATION_COLUMNS = 25`.

### 4. `assess_quality` - read_only

**Description:** "Get the data-quality warnings and recommended fixes for this dataset."

- **Arguments:** none
- **Wraps:** `app/services/profiling_service.py` → `ProfilingService.full_profile(df,
  size_bytes)`
- **Note:** `full_profile` returns twelve top-level keys and is easily tens of kilobytes.
  The tool must return **only** `quality`, `warnings` and `recommendations`.

### 5. `run_query` - read_only

**Description:** "Aggregate the data to answer a quantitative question - totals or
averages by category, or a measure over time."

- **Arguments:**
  - `measure: str | None` - numeric column to aggregate
  - `aggregation: "sum" | "avg" | "count" | "min" | "max" | "median"` (default `"sum"`)
  - `dimension: str | None` - column to group by
  - `date_column: str | None`
  - `time_grain: "day" | "week" | "month" | "quarter" | "year"` (default `"month"`)
  - `top_n: int` - 1 to 100 (default 10)
  - `chart_type: "line" | "area" | "bar" | "horizontal_bar" | "pie" | "scatter" | "histogram" | "table" | "kpi"` (default `"bar"`)
  - `secondary_measure: str | None` - second numeric column, scatter only
- **Wraps:** `app/services/analytics_service.py` → `AnalyticsService.run_query(df,
  query)` (singleton `analytics_service`), with the arguments assembled into an
  `AnalyticsQuery` from `app/schemas.py:229`
- **Note:** do not expose `use_cleaned` - which file is read is our decision, not the
  model's. `_validate` already refuses invalid combinations with a reason; pass its
  `error_code` straight back as the tool result.

### 6. `recommend_cleaning` - read_only

**Description:** "See what cleaning this dataset needs and why. This only inspects the
data; it changes nothing."

- **Arguments:** none
- **Wraps:** `app/services/cleaning_service.py` → `CleaningService.recommend_config(df)`
  (singleton `cleaning_service`)
- **Returns:** `recommended_config` plus the reason for each choice.

### 7. `get_model_results` - read_only

**Description:** "Get the results of the most recent model training run for this
dataset, including the best model and its scores."

- **Arguments:** none
- **Wraps:** `app/services/ml_service.py` → `MLService.latest_run(dataset_id, user_id)`,
  with `MLService.history(dataset_id, user_id)` for prior versions
- **Note:** `latest_run` takes an **int id, not a `Dataset`**, and returns an ORM
  `models.ModelRun`, so the wrapper must serialise it; `history` is already
  `to_jsonable`. When nothing has been trained it returns `None`, which the tool reports
  as "no model trained yet" rather than as an error.

### 8. `explain_model` - read_only

**Description:** "Explain which columns most influence the trained model's predictions."

- **Arguments:** none
- **Wraps:** `app/services/explainability_service.py` →
  `ExplainabilityService.explain(dataset, user_id)`
- **Note:** raises `NotFoundError(error_code="no_trained_model")` when no run exists -
  catch it and return a result telling the model to train first. Truncate
  `feature_importance` to roughly the top 15 entries.

### 9. `apply_cleaning` - **action** (requires `allow_actions=true`)

**Description:** "Apply the recommended cleaning to this dataset, writing a cleaned copy.
The original upload is kept and this can be reverted."

- **Arguments:** none - it applies the config from `recommend_config`, so the model
  cannot hand-craft a destructive combination
- **Wraps:** `app/services/cleaning_service.py` → `CleaningService.apply_config(df,
  config)`, **plus a persistence step that currently has no service function** - see
  Mismatch 1. Today that sequence lives in `app/cleaning.py:64-74`.
- **Note:** reversible through the existing `POST /{id}/clean/revert`.

### 10. `train_model` - **action** (requires `allow_actions=true`)

**Description:** "Train and compare models to predict a target column, and return the
leaderboard."

- **Arguments:**
  - `target_column: str | None` - omit to let InsightFlow choose
  - `task_type: "auto" | "classification" | "regression"` (default `"auto"`)
- **Wraps:** `app/services/ml_service.py` → `MLService.train(dataset, user_id,
  request)`, with the arguments assembled into a `TrainRequest` from
  `app/schemas.py:270`
- **Note:** must call `check_training_rate(db, user_id)` from `app/core/limits.py`
  first. Only these two fields are exposed; `test_size`, `cross_validation_folds`,
  `enable_tuning` and `use_cleaned` keep their defaults so the model cannot quietly
  weaken the evaluation.

### Gating

When `allow_actions` is false, tools 9 and 10 are **omitted from the tool array
entirely** rather than advertised and then refused. A tool the model cannot use should
not be in its list. The `blocked_action` step status exists for the defensive case where
a call for them arrives anyway.

## Mismatches between intended tools and real functions

Six, all verified against the code. None of these are invented functions; each is a
place where the intended design does not fit what exists.

1. **`apply_cleaning` has no service function to wrap.** `cleaning_service.apply_config`
   is pure and persists nothing. The write sequence lives in `app/cleaning.py:64-74` and
   is duplicated in `app/services/agent_service.py:118-124`, and the two **disagree**:
   the route sets `dataset.cleaning_log = report.get("steps", [])`, Guided Analysis does
   not. Options: (a) extract one method, e.g.
   `CleaningService.apply_and_persist(db, dataset, config)`, and call it from all three
   places - fixes the existing divergence but edits two files you asked me not to
   disturb; (b) have the tool call the route function `cleaning.apply_cleaning(body,
   dataset, db)` directly, which is importable but couples a service to a router; (c)
   duplicate the seven lines a third time, which contradicts "do not duplicate logic".
   **Needs your decision - I recommend (a).**
2. **`_sanitize` cannot be used on tool results as-is.** It ends with
   `return cleaned[:MAX_CELL_LENGTH]`, a hard 120-character cut. Correct for a column
   name, destructive for a JSON result blob. Plan: reuse `INJECTION_PATTERNS` and the
   `<<<`/`>>>` fence-stripping, but with a separate, larger result budget
   (`AGENT_MAX_TOOL_RESULT_CHARS`, suggest 4000). `_sanitize` itself stays untouched.
3. **`LLMProvider.chat` discards what the agent needs.** It returns
   `choices[0]["message"]["content"].strip()` - a `str` - so `tool_calls` and the `usage`
   block are gone. Since `agent_steps` must record token usage, `chat_with_tools` has to
   be a **new sibling method** reading the raw message and usage. `chat()` is not
   modified, so the Copilot is unaffected.
4. **`get_model_results` → `latest_run` returns an ORM object**, not a dict, unlike
   almost every other service call here. The wrapper must serialise it (or prefer
   `history()`, which is already `to_jsonable`).
5. **The intended `run_query` argument list is incomplete.** It omits `chart_type`,
   which selects the execution branch (`kpi`, `histogram`, `scatter`, time series,
   grouped), and `secondary_measure`, without which `scatter` cannot run. Both are added
   above.
6. **`check_copilot_rate` counts rows the agent will never write.** It counts
   `ChatMessage` where `role == "user"`; the agent persists to `agent_runs` instead.
   Reusing it verbatim means agent traffic is capped by Copilot history but never adds to
   it - the cap would not actually limit the agent. Carried into Open questions.

## Tracing tables

Conventions verified against `app/models.py` (read in full). The project uses the
classic `Column(...)` style, **not** 2.0 `Mapped`/`mapped_column`, so the new tables must
match:

```python
from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, JSON,
                        String, Text, Index)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

id         = Column(Integer, primary_key=True, index=True)
user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False, index=True)
dataset_id = Column(Integer, ForeignKey("datasets.id", ondelete="CASCADE"),
                    nullable=False, index=True)
created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
__table_args__ = (Index("ix_model_runs_dataset_version", "dataset_id", "version"),)
```

Three things follow from that:

- **Parent-side relationships must be added too.** Every child table in this schema is
  paired with a `relationship(..., back_populates=..., cascade="all, delete-orphan")` on
  both `User` and `Dataset` (see `models.py:47-64` and `109-120`). `AgentRun` should
  follow suit, which means editing `User` and `Dataset` to add `agent_runs`. That is
  additive and changes no existing behaviour, but it does touch `models.py`.
- **Migration head is `b3g2d4e5f6a7`.** The chain is
  `61f00253b63b` → `b2c4d6e8f0a1` → `b3g2d4e5f6a7`, single head, no branches. The new
  migration sets `down_revision = 'b3g2d4e5f6a7'`.
- **SQLite is fine here.** The earlier `b3g2d4e5f6a7` migration had to avoid
  `batch_alter_table` and drop a self-referential foreign key because SQLite cannot ALTER
  constraints. That constraint does not apply to these two tables: they are created with
  `op.create_table`, where SQLite accepts foreign keys inline.

### `agent_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer, PK, indexed | |
| `dataset_id` | Integer, FK `datasets.id`, indexed, not null | cascade delete with the dataset |
| `user_id` | Integer, FK `users.id`, indexed, not null | |
| `question` | Text, not null | the user's question as asked |
| `answer` | Text, nullable | null when the run failed or hit the step cap |
| `allow_actions` | Boolean, not null, default False | what the request permitted |
| `status` | String, not null | `completed` \| `max_steps_reached` \| `failed` \| `circuit_open` |
| `error_code` | String, nullable | mirrors the `AppException` code when status is `failed` |
| `steps_used` | Integer, not null, default 0 | |
| `prompt_tokens` | Integer, nullable | summed across LLM calls |
| `completion_tokens` | Integer, nullable | |
| `duration_ms` | Integer, nullable | whole run |
| `model` | String, nullable | `settings.GROQ_MODEL` at run time, so old traces stay interpretable |
| `created_at` | DateTime(timezone=True), server default now | |

### `agent_steps`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer, PK, indexed | |
| `run_id` | Integer, FK `agent_runs.id`, indexed, not null | cascade delete with the run |
| `step_index` | Integer, not null | 0-based, ordering within the run |
| `tool_name` | String, nullable | null for a step that produced only text |
| `arguments` | JSON, nullable | exactly what the model asked for, **before** validation |
| `status` | String, not null | `ok` \| `invalid_arguments` \| `tool_error` \| `blocked_action` \| `rejected_unknown_tool` |
| `error_code` | String, nullable | |
| `result_chars` | Integer, nullable | size before truncation, so trace shows what was cut |
| `redacted` | Boolean, not null, default False | true when `INJECTION_PATTERNS` fired inside the tool result |
| `duration_ms` | Integer, nullable | tool execution only |
| `prompt_tokens` | Integer, nullable | for the LLM call that chose this tool |
| `completion_tokens` | Integer, nullable | |
| `created_at` | DateTime(timezone=True), server default now | |

`arguments` is stored pre-validation and `redacted` is stored per step deliberately: both
are what make an injection attempt or a bad-argument loop reconstructable afterwards.

## Route and wiring

The existing route, `app/agent.py`, is a 37-line file whose router is declared
`APIRouter(prefix="/datasets", tags=["guided-analysis"])` with one endpoint,
`POST /{dataset_id}/agent/run`.

**Recommendation: a new file `app/tool_agent.py`, not an addition to `agent.py`.**
Adding `/agent/ask` to the existing router would file it under the
`guided-analysis` OpenAPI tag, which is actively misleading - the whole point of Phase 1
is that this is a different thing from the fixed pipeline. A new module with
`APIRouter(prefix="/datasets", tags=["ai-agent"])` leaves `agent.py` byte-for-byte
unchanged and gives the new endpoint its own section in the docs.

It must copy `agent.py`'s dependency set exactly:

```python
@router.post("/{dataset_id}/agent/ask")
def ask_agent(
    body: schemas.AgentAskRequest,
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # Imported on first use: the registry reaches ML/explain code, which pulls
    # in scikit-learn (see app/ml.py).
    from .services.tool_agent_service import ToolAgentService

    return ToolAgentService(db).ask(
        dataset, current_user.id,
        question=body.question, allow_actions=body.allow_actions,
    )
```

The lazy import inside the function body is not optional - it is the pattern `ml.py`,
`agent.py`, `explain.py` and `report.py` all follow to keep scikit-learn off the
cold-start path, and `tool_registry.py` will transitively import `MLService`.

New schemas for `app/schemas.py` (additive):

```python
class AgentAskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    allow_actions: bool = False

class AgentStepOut(BaseModel):
    step_index: int
    tool_name: str | None
    arguments: dict[str, Any] | None
    status: str
    error_code: str | None = None
    duration_ms: int | None = None
    redacted: bool = False

class AgentAskOut(BaseModel):
    run_id: int
    answer: str | None
    status: str
    steps_used: int
    steps: list[AgentStepOut]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
```

New settings for `app/core/config.py` (additive, all defaulted so nothing breaks):

```python
AGENT_MAX_STEPS: int = 6
AGENT_MAX_TOOL_RESULT_CHARS: int = 4000
AGENT_MAX_TOTAL_TOKENS: int = 30_000
```

`main.py` mounts every router twice - at its legacy unprefixed path and under
`/api/v1/...` - so the new router needs registering in both places alongside the others.

## Test plan

`backend/tests/conftest.py`, read in full. What it gives and what it constrains:

- `client` → `TestClient(app)`.
- `auth_headers` → **returns a tuple `(headers, tokens)`**, not a dict. Existing tests
  unpack it. Easy to get wrong.
- `fresh_db` is `autouse` and calls `Base.metadata.create_all` / `drop_all` per test, so
  **`agent_runs` and `agent_steps` appear in tests automatically from the model
  definitions.** The Alembic migration is required for real deployments but is not what
  makes the tests pass - CI verifies it separately with `python -m alembic upgrade head`.
- `reset_rate_limiter` is `autouse`, so slowapi buckets do not leak between tests.
- Env is pinned before `app` is imported: `DATABASE_URL` to a SQLite file, `JWT_SECRET`,
  `ENVIRONMENT=test`.

**The constraint that shapes every agent test:** `GROQ_API_KEY` is *not* set in
`conftest.py`, and `settings.copilot_enabled` is a property returning
`bool(self.GROQ_API_KEY)` (`config.py:107-111`). So out of the box the agent route will
return the "not configured" 503, exactly as `test_copilot_ask_without_key_returns_actionable_error`
already relies on. Each agent test must therefore
`monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")` - which flips
`copilot_enabled` to True for free - and monkeypatch the provider so no network call
happens.

Mock shape: patch `_build_provider` (or inject a provider) with a fake whose
`chat_with_tools` returns a **scripted list of responses**, popped one per call. That is
what lets a test assert a multi-step trace deterministically.

Planned cases, one per requirement the owner listed:

| Test | Asserts |
|---|---|
| `test_agent_picks_the_expected_tool` | scripted single tool call → `agent_steps` records `tool_name`, and the answer comes back |
| `test_agent_stops_at_max_steps` | provider always asks for another tool → run ends with `status="max_steps_reached"` and `steps_used == AGENT_MAX_STEPS` |
| `test_unknown_column_returns_error_result_not_500` | `profile_column(column="nope")` → HTTP 200, step status `tool_error`, and the model receives the valid column list |
| `test_invalid_tool_arguments_are_rejected` | bad types for `run_query` → step status `invalid_arguments`, no exception escapes |
| `test_injection_text_in_tool_result_is_redacted` | dataset cell containing "ignore all previous instructions" → step `redacted=True` and the fenced result carries the redaction marker |
| `test_action_tools_blocked_without_allow_actions` | `allow_actions=False` → `apply_cleaning`/`train_model` are absent from the advertised tool array, and a forced call is recorded `blocked_action` with no state change |
| `test_action_tools_run_with_allow_actions` | `allow_actions=True` → `apply_cleaning` writes a cleaned copy and `dataset.cleaned_path` is set |
| `test_train_model_respects_training_rate_limit` | `MAX_TRAINING_JOBS_PER_HOUR` exhausted → `RateLimitedError` surfaces as a tool error, not a 500 |
| `test_other_users_dataset_returns_404` | second user's dataset id → 404 via `get_owned_dataset`; add the new path to `TestCrossTenantIsolation`'s parametrised list in `test_security.py` |
| `test_circuit_breaker_blocks_after_repeated_failures` | three provider failures → `copilot_circuit_open`, 503 |
| `test_trace_is_returned_in_the_response` | response `steps` match the persisted `agent_steps` rows |

## Lint and CI constraints

There is **no `pyproject.toml`, `ruff.toml` or `setup.cfg`** anywhere in the repo. Ruff
is driven entirely by the flags in `.github/workflows/ci.yml`:

```
pip install ruff==0.16.3
ruff check --select E4,E7,E9,F app/ tests/
ruff format --check app/ tests/
python -m pytest -x -q --tb=short
python -m alembic upgrade head
```

Consequences for Phase 1:

- `ruff format` runs with **default settings, so line length is 88.** This is also why
  the old `F:\InsightFlow\InsightFlow` copy differs from the published repo in all 41
  files: it predates the formatter being enforced. New files must be written
  format-clean or CI fails on `--check`.
- The enabled rule set is narrow (`E4` imports, `E7`, `E9`, `F` pyflakes). Unused imports
  (`F401`) will fail, so the lazy-import pattern must not leave stray module-level
  imports behind.
- `pytest -x` means the suite stops at the first failure.
- CI runs the migration, so `down_revision = 'b3g2d4e5f6a7'` must be correct or the
  `Database migrations` job fails.

## Answered questions

**Test count.** `python -m pytest --collect-only -q` in
`F:\InsightFlow - Publish\InsightFlow\backend` reports:

```
106 tests collected in 0.15s
```

So the CV's "106 automated tests" is accurate for the GitHub repo. The upgrade plan's
observation that the old local copy has 90 `def test_` functions is also accurate and
not a contradiction: `test_security.py` parametrises several cases (14 of them on
`test_user_cannot_access_other_users_dataset_get` alone), and pytest counts the expanded
cases. Use **106 collected tests** as the figure, and expect it to rise with the Phase 1
tests.

## Open questions

Both questions you asked me to answer are resolved above: the repo is
`F:\InsightFlow - Publish\InsightFlow` (confirmed via `git remote -v` →
`github.com/jenil38/insightflow.git`), and the real test count is **106 collected**.

These are the decisions I should not make for you.

1. **How `apply_cleaning` persists.** The blocker from Mismatch 1. No service function
   writes the cleaned copy; the sequence is duplicated in `app/cleaning.py:64-74` and
   `app/services/agent_service.py:118-124`, and they disagree about `cleaning_log`.
   My recommendation is to extract `CleaningService.apply_and_persist(db, dataset,
   config)` and call it from all three sites, which also fixes the existing divergence.
   That edits two files you told me not to disturb - behaviour-preserving, but your call.
   The alternatives are importing the route function into a service, or a third copy of
   the logic.

2. **Rate limiting source of truth.** `check_copilot_rate` counts `ChatMessage` rows with
   `role == "user"`, and the agent will not create those rows. Options: (a) reuse it
   as-is, so Copilot history throttles the agent but agent calls never consume the
   budget - meaning the cap does not really limit the agent; (b) add a sibling
   `check_agent_rate` counting `agent_runs` in the last hour; (c) have the agent also
   write to `ChatMessage`. I recommend (b). (a) is what "reuse the existing limit" says
   literally, but it leaves the agent effectively uncapped.

3. **May I add two relationships to `models.py`?** `AgentRun` should be reachable as
   `User.agent_runs` and `Dataset.agent_runs` with `cascade="all, delete-orphan"`, which
   is how every other child table in this schema is wired. It is additive and changes no
   behaviour, but it does mean editing `models.py`. Without it, deleting a dataset would
   leave orphan `agent_runs` rows relying on the database-level `ON DELETE CASCADE`
   alone - which actually still works, so this is a consistency choice, not a bug fix.

4. **Is the frontend Agent tab in Phase 1?** Item 6 of your plan mentions "a small Agent
   tab that shows the answer and the step trace". I have scoped and costed the backend
   only. Say if you want the tab in this phase or deferred.

5. **`AGENT_MAX_STEPS = 6` with `train_model` enabled.** A training call can take tens of
   seconds, and the step budget does not distinguish a cheap profiling call from an
   expensive training one. Options: keep one flat budget; or give action tools their own
   smaller allowance. I would start flat at 6 and revisit once Phase 3 measures real step
   counts, rather than inventing a second budget now.

6. **Does Groq actually return well-formed `tool_calls` on `llama-3.3-70b-versatile`?**
   Unverified, and it cannot be verified by the Phase 1 tests because they mock the
   provider by design. The first real API call is the moment of truth. If the model
   returns malformed arguments often, the loop needs a retry-with-feedback step that is
   not in this plan.
