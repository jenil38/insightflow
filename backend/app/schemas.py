"""
Pydantic request/response schemas.

Existing schemas (UserCreate, UserOut, Token, LoginRequest, DatasetOut, Page)
keep their original field shapes so the current frontend keeps working
untouched. New fields/schemas are additive.
"""

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .core.security import validate_password_complexity

T = TypeVar("T")

# Several response models expose counts named `model_run_count` / `latest_model_*`.
# Pydantic v2 reserves the `model_` prefix for its own methods and warns on any
# field using it, so the models below opt out of that protected namespace rather
# than renaming fields the API contract depends on.
_ALLOW_MODEL_PREFIX = ConfigDict(from_attributes=True, protected_namespaces=())


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str | None = None
    password: str

    @field_validator("password")
    @classmethod
    def _check_password_complexity(cls, v: str) -> str:
        validate_password_complexity(v)
        return v


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None = None
    is_verified: bool = False
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = Field(
        default=None,
        description="Access-token lifetime in seconds, so clients can refresh proactively.",
    )


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_password_complexity(cls, v: str) -> str:
        validate_password_complexity(v)
        return v


class EmailVerifyRequest(BaseModel):
    token: str


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


class DatasetOut(BaseModel):
    id: int
    filename: str
    file_type: str
    rows: int | None
    columns: int | None
    size_bytes: int | None
    uploaded_at: datetime | None = None

    class Config:
        from_attributes = True


class DatasetListItem(DatasetOut):
    """Row shape for the datasets table on the home page - adds the status
    columns the table shows, without a per-row extra request."""

    model_config = _ALLOW_MODEL_PREFIX

    has_cleaned_version: bool = False
    model_run_count: int = 0
    latest_model_name: str | None = None


class DatasetDetail(DatasetOut):
    """Everything the workspace header needs, in one request."""

    model_config = _ALLOW_MODEL_PREFIX

    has_cleaned_version: bool = False
    active_source: Literal["original", "cleaned"] = "original"
    model_run_count: int = 0
    latest_model_name: str | None = None
    latest_model_version: int | None = None
    latest_model_trained_at: datetime | None = None
    report_count: int = 0
    chat_message_count: int = 0


class UserSummary(BaseModel):
    """Per-user totals for the home dashboard. Scoped to the authenticated
    user - deliberately distinct from the global /metrics endpoint."""

    model_config = _ALLOW_MODEL_PREFIX

    dataset_count: int
    total_rows: int
    total_columns: int
    total_storage_bytes: int
    latest_upload_at: datetime | None = None
    model_run_count: int
    report_count: int
    cleaned_dataset_count: int


class Page(BaseModel, Generic[T]):
    """Generic pagination envelope. Only used where an endpoint opts into
    pagination via ?page=&page_size= - existing unpaginated responses are
    left as plain lists for backward compatibility."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class PreviewResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    page: int
    page_size: int
    total_pages: int
    source: Literal["original", "cleaned"]
    sort_by: str | None = None
    sort_dir: Literal["asc", "desc"] = "asc"
    search: str | None = None


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

NumericMissingStrategy = Literal["median", "mean", "zero", "drop", "leave"]
CategoricalMissingStrategy = Literal["mode", "unknown", "drop", "leave"]
OutlierStrategy = Literal["report", "cap", "remove", "leave"]
CaseStrategy = Literal["none", "lower", "upper", "title"]


class CleaningConfig(BaseModel):
    """Every cleaning transformation is opt-in, and the whole operation is
    reversible by discarding the cleaned file (POST /clean/revert).

    Defaults reproduce the original pipeline's *safe* behaviour. Note that
    `standardize_case` defaults to "none": the original code lower-cased all
    text silently, which is lossy, so it now requires an explicit choice.
    """

    remove_duplicates: bool = True
    trim_whitespace: bool = True
    normalize_whitespace: bool = True
    standardize_case: CaseStrategy = "none"
    parse_dates: bool = True
    numeric_missing_strategy: NumericMissingStrategy = "median"
    categorical_missing_strategy: CategoricalMissingStrategy = "mode"
    outlier_strategy: OutlierStrategy = "report"
    drop_empty_columns: bool = False


class CleaningRequest(BaseModel):
    config: CleaningConfig = Field(default_factory=CleaningConfig)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

Aggregation = Literal["sum", "avg", "count", "min", "max", "median"]
TimeGrain = Literal["day", "week", "month", "quarter", "year"]
ChartType = Literal[
    "line",
    "area",
    "bar",
    "horizontal_bar",
    "pie",
    "scatter",
    "histogram",
    "table",
    "kpi",
]


class AnalyticsQuery(BaseModel):
    measure: str | None = Field(
        default=None,
        description="Numeric column to aggregate. Omit for count-only queries.",
    )
    aggregation: Aggregation = "sum"
    dimension: str | None = Field(default=None, description="Column to group by.")
    date_column: str | None = None
    time_grain: TimeGrain = "month"
    top_n: int = Field(default=10, ge=1, le=100)
    chart_type: ChartType = "bar"
    secondary_measure: str | None = Field(
        default=None, description="Second numeric column, used by scatter plots."
    )
    use_cleaned: bool = True


class DashboardLayoutIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    is_default: bool = False


class DashboardLayoutOut(BaseModel):
    id: int
    dataset_id: int
    name: str
    charts: list[dict[str, Any]]
    is_default: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Machine learning
# ---------------------------------------------------------------------------


class TrainRequest(BaseModel):
    """Every field is optional: an empty body reproduces the original fully
    automatic behaviour (auto target, auto task type, tuning on)."""

    target_column: str | None = None
    task_type: Literal["auto", "classification", "regression"] = "auto"
    excluded_columns: list[str] = Field(default_factory=list)
    test_size: float = Field(default=0.2, ge=0.05, le=0.5)
    cross_validation_folds: int = Field(default=5, ge=2, le=10)
    enable_tuning: bool = True
    use_cleaned: bool = True


class ModelRunOut(BaseModel):
    id: int
    version: int
    best_model_name: str | None
    task_type: str | None
    target_column: str | None
    metrics: dict[str, Any] | None
    config: dict[str, Any] | None = None
    features: list[str] | None = None
    data_source: str | None = None
    rows_used: int | None = None
    has_model_file: bool = False
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class TrainConfigOptions(BaseModel):
    """Everything the pre-training configuration screen needs, computed from the
    dataset so the user picks from real columns instead of typing names."""

    columns: list[dict[str, Any]]
    target_candidates: list[dict[str, Any]]
    recommended_target: str | None
    recommended_task_type: str | None
    suggested_exclusions: list[dict[str, str]]
    warnings: list[dict[str, Any]]
    row_count: int
    data_source: str


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ChatMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class ChatResponse(BaseModel):
    answer: str
    columns_referenced: list[str] = Field(default_factory=list)
    message_id: int | None = None


class SuggestedQuestions(BaseModel):
    questions: list[str]
    copilot_enabled: bool


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class ReportRecordOut(BaseModel):
    id: int
    format: str
    created_at: datetime | None = None

    class Config:
        from_attributes = True
