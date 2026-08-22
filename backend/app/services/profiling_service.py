"""
Dataset profiling and data-quality scoring.

Every score here is a documented arithmetic formula over observable counts -
there is no opaque "AI score". The formulas are returned to the client
(`score_definitions`) so the UI can show the user exactly how each number was
derived.

Scoring model
-------------
completeness = 100 * (non-null cells / total cells)
uniqueness   = 100 * (columns carrying usable variation / total columns);
               a column fails only if it is empty, constant, or >95% one value
duplicates   = 100 * (1 - duplicate rows / total rows)
consistency  = 100 * mean over text columns of the dominant-inferred-type share
overall      = 0.35*completeness + 0.30*duplicates + 0.20*consistency + 0.15*uniqueness

The weights favour completeness and duplicate-freedom because those two
dominate whether a dataset is usable for modelling.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..core.config import settings
from ..core.serialization import safe_float, safe_int, to_jsonable

SCORE_WEIGHTS = {
    "completeness": 0.35,
    "duplicates": 0.30,
    "consistency": 0.20,
    "uniqueness": 0.15,
}

SCORE_DEFINITIONS = {
    "completeness": "100 x (non-null cells / total cells).",
    "uniqueness": (
        "Share of columns carrying usable variation. A column counts against this "
        "only if it is empty, holds a single value, or is more than 95% one value - "
        "a genuinely low-cardinality column like a region code is not a defect."
    ),
    "duplicates": "100 x (1 - duplicate rows / total rows).",
    "consistency": (
        "For each text column, the share of non-null values matching that column's "
        "dominant inferred type (number, date, or text), averaged across text "
        "columns. Columns that are already strongly typed score 100."
    ),
    "overall": (
        "Weighted average: 35% completeness, 30% duplicate-freedom, "
        "20% type consistency, 15% uniqueness."
    ),
}

# Outcome-name evidence is tiered, because these terms are not equally
# diagnostic. "revenue" or "churn" is almost always the thing being predicted;
# "amount" or "cost" is just as often an input feature. Without tiers, a dataset
# containing both `spend` and `revenue` scores them identically and the
# recommendation falls back to column order - which picked `spend` as the target
# and then used `revenue` to predict it.
STRONG_TARGET_KEYWORDS = (
    "revenue",
    "sales",
    "profit",
    "churn",
    "target",
    "label",
    "outcome",
    "converted",
    "conversion",
    "default",
    "fraud",
    "survived",
)
WEAK_TARGET_KEYWORDS = (
    "price",
    "amount",
    "total",
    "score",
    "rating",
    "value",
    "cost",
    "spend",
    "count",
)
ID_KEYWORDS = ("id", "uuid", "guid", "key", "code", "ref", "index")

# A text column with more distinct values than this share of its rows is treated
# as free text / an identifier rather than a category.
HIGH_CARDINALITY_RATIO = 0.5
NEAR_CONSTANT_RATIO = 0.95


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------


def infer_semantic_type(series: pd.Series) -> str:
    """Coarse type used throughout the UI:
    numeric | datetime | boolean | categorical | text | empty."""
    non_null = series.dropna()
    if non_null.empty:
        return "empty"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"

    sample = non_null.head(200)
    if _parses_as_datetime(sample):
        return "datetime"
    if _parses_as_numeric(sample):
        return "numeric"

    distinct_ratio = non_null.nunique() / len(non_null)
    return "text" if distinct_ratio > HIGH_CARDINALITY_RATIO else "categorical"


def _parses_as_datetime(sample: pd.Series) -> bool:
    if sample.empty or pd.api.types.is_numeric_dtype(sample):
        # Bare integers parse as epoch datetimes but almost never mean one.
        return False
    try:
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    except (ValueError, TypeError):
        return False
    return bool(parsed.notna().mean() >= 0.9)


def _parses_as_numeric(sample: pd.Series) -> bool:
    if sample.empty:
        return False
    return bool(pd.to_numeric(sample, errors="coerce").notna().mean() >= 0.9)


def detect_datetime_columns(df: pd.DataFrame) -> list[str]:
    return [str(c) for c in df.columns if infer_semantic_type(df[c]) == "datetime"]


def detect_numeric_columns(df: pd.DataFrame) -> list[str]:
    return [str(c) for c in df.select_dtypes(include=[np.number]).columns]


def detect_categorical_columns(df: pd.DataFrame) -> list[str]:
    return [str(c) for c in df.columns if infer_semantic_type(df[c]) == "categorical"]


def infer_task_type(series: pd.Series, semantic: str, distinct: int) -> str:
    """classification | regression.

    A continuous column is a regression target even when the sample happens to
    hold few distinct values - a float revenue column with 10 rows is still
    regression, not a 10-class problem. Only integer-like or genuinely
    categorical columns with a small class count become classification.
    """
    if semantic in ("categorical", "boolean"):
        return "classification"
    if semantic == "numeric":
        non_null = series.dropna()
        is_whole = pd.api.types.is_integer_dtype(non_null) or (
            pd.api.types.is_float_dtype(non_null)
            and not non_null.empty
            and bool((non_null % 1 == 0).all())
        )
        if is_whole and distinct <= 15:
            return "classification"
        return "regression"
    return "classification"


def is_continuous(series: pd.Series) -> bool:
    """True for float-valued numeric columns that aren't whole numbers.

    Used to distinguish a measurement from a code: a continuous column is
    *expected* to be unique per row, so uniqueness says nothing about whether
    it's an identifier.
    """
    non_null = series.dropna()
    if non_null.empty or not pd.api.types.is_numeric_dtype(non_null):
        return False
    if pd.api.types.is_integer_dtype(non_null) or pd.api.types.is_bool_dtype(non_null):
        return False
    return not bool((non_null % 1 == 0).all())


def _looks_like_identifier(
    column: str, distinct: int, non_null: int, series: pd.Series
) -> bool:
    """Identifier-like columns make poor targets and poor features.

    Two signals: a name that reads like a key, or full uniqueness. The
    uniqueness test deliberately excludes continuous columns - a float revenue
    column is unique on almost every row, and treating that as an identifier
    would exclude the single most likely target in the dataset.
    """
    tokens = str(column).lower().replace("-", "_").split("_")
    if any(tok in ID_KEYWORDS for tok in tokens):
        return True
    fully_unique = distinct == non_null and non_null > 10
    return fully_unique and not is_continuous(series)


# ---------------------------------------------------------------------------
# Target recommendation
# ---------------------------------------------------------------------------


def recommend_targets(df: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]]:
    """Rank candidate prediction targets, each with a stated reason.

    Confidence is a heuristic in [0, 1] built from additive evidence, not a
    trained estimate - the `reason` string always says what drove it.
    """
    candidates: list[dict[str, Any]] = []
    last_column = str(df.columns[-1]) if len(df.columns) else None

    for col in df.columns:
        series = df[col]
        semantic = infer_semantic_type(series)
        if semantic in ("empty", "text", "datetime"):
            continue

        non_null = series.dropna()
        if non_null.empty:
            continue

        distinct = int(non_null.nunique())
        if distinct < 2:
            continue  # a constant column predicts nothing
        if _looks_like_identifier(col, distinct, len(non_null), series):
            continue  # identifier-like: never a sensible target

        lowered = str(col).lower()
        reasons: list[str] = []
        confidence = 0.30

        if any(k in lowered for k in STRONG_TARGET_KEYWORDS):
            confidence += 0.35
            reasons.append("its name is a strong outcome term")
        elif any(k in lowered for k in WEAK_TARGET_KEYWORDS):
            # Deliberately weaker: these words appear on inputs as often as on outcomes.
            confidence += 0.15
            reasons.append("its name suggests a measure, which is often an outcome")

        # Datasets conventionally put the label last. Worth a nudge, not a decision.
        if last_column is not None and str(col) == last_column:
            confidence += 0.04
            reasons.append("it is the last column, where labels usually sit")

        if semantic == "numeric":
            confidence += 0.10
            reasons.append("it is numeric, so it can be regressed on")
            variance = safe_float(non_null.var(), digits=6)
            if variance and variance > 0:
                confidence += 0.05
                reasons.append("its values vary across rows")
        else:  # categorical / boolean
            if 2 <= distinct <= 15:
                confidence += 0.15
                reasons.append(
                    f"it has {distinct} distinct classes, suitable for classification"
                )
            else:
                confidence -= 0.10
                reasons.append(
                    f"it has {distinct} classes, which is many for classification"
                )

        completeness = len(non_null) / max(len(series), 1)
        if completeness < 0.8:
            confidence -= 0.15
            reasons.append(f"only {completeness:.0%} of its values are present")
        else:
            confidence += 0.05

        candidates.append(
            {
                "column": str(col),
                "semantic_type": semantic,
                "task_type": infer_task_type(series, semantic, distinct),
                "distinct_values": distinct,
                "confidence_pct": round(max(0.05, min(confidence, 0.97)) * 100, 1),
                "reason": ("Suggested because " + ", and ".join(reasons) + ".")
                if reasons
                else "Usable as a target.",
            }
        )

    candidates.sort(key=lambda c: c["confidence_pct"], reverse=True)
    return candidates[:limit]


def guess_target_column(df: pd.DataFrame) -> tuple[str | None, float]:
    """Backward-compatible signature used by the original modules: returns
    (column_name, confidence_as_fraction)."""
    ranked = recommend_targets(df, limit=1)
    if not ranked:
        numeric = detect_numeric_columns(df)
        return (numeric[0], 0.3) if numeric else (None, 0.0)
    top = ranked[0]
    return top["column"], top["confidence_pct"] / 100.0


# ---------------------------------------------------------------------------
# Column-level profile
# ---------------------------------------------------------------------------


def profile_column(
    df: pd.DataFrame, column: str, histogram_bins: int = 12
) -> dict[str, Any]:
    series = df[column]
    total = int(len(series))
    non_null_series = series.dropna()
    non_null = int(len(non_null_series))
    missing = total - non_null
    semantic = infer_semantic_type(series)

    profile: dict[str, Any] = {
        "column": str(column),
        "dtype": str(series.dtype),
        "semantic_type": semantic,
        "total_count": total,
        "non_null_count": non_null,
        "missing_count": missing,
        "missing_pct": safe_float(missing / total * 100, 2) if total else 0.0,
        "unique_count": int(non_null_series.nunique()) if non_null else 0,
        "unique_pct": safe_float(non_null_series.nunique() / non_null * 100, 2)
        if non_null
        else 0.0,
        "is_constant": non_null > 0 and non_null_series.nunique() <= 1,
        "example_values": [to_jsonable(v) for v in non_null_series.head(5).tolist()],
        "min": None,
        "max": None,
        "mean": None,
        "median": None,
        "std": None,
        "q1": None,
        "q3": None,
        "outlier_count": None,
        "top_values": [],
        "histogram": [],
    }

    if non_null == 0:
        return profile

    if semantic == "numeric" and pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(non_null_series, errors="coerce").dropna()
        if not numeric.empty:
            profile.update(
                {
                    "min": safe_float(numeric.min()),
                    "max": safe_float(numeric.max()),
                    "mean": safe_float(numeric.mean()),
                    "median": safe_float(numeric.median()),
                    "std": safe_float(numeric.std()),
                    "q1": safe_float(numeric.quantile(0.25)),
                    "q3": safe_float(numeric.quantile(0.75)),
                    "outlier_count": iqr_outlier_count(numeric),
                }
            )
            profile["histogram"] = numeric_histogram(numeric, bins=histogram_bins)
    elif semantic == "datetime":
        parsed = pd.to_datetime(
            non_null_series, errors="coerce", format="mixed"
        ).dropna()
        if not parsed.empty:
            profile["min"] = to_jsonable(parsed.min())
            profile["max"] = to_jsonable(parsed.max())

    counts = non_null_series.value_counts().head(10)
    profile["top_values"] = [
        {
            "value": to_jsonable(value),
            "count": int(count),
            "pct": safe_float(count / non_null * 100, 2),
        }
        for value, count in counts.items()
    ]
    if semantic in ("categorical", "boolean") and not profile["histogram"]:
        profile["histogram"] = [
            {"bin": str(v["value"]), "count": v["count"]} for v in profile["top_values"]
        ]

    return profile


def iqr_outlier_count(numeric: pd.Series) -> int:
    """Count values outside 1.5x the interquartile range."""
    if len(numeric) < 4:
        return 0
    q1, q3 = numeric.quantile(0.25), numeric.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0 or pd.isna(iqr):
        return 0
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return int(((numeric < lower) | (numeric > upper)).sum())


def numeric_histogram(numeric: pd.Series, bins: int = 12) -> list[dict[str, Any]]:
    finite = numeric[np.isfinite(numeric)]
    if finite.empty:
        return []
    if finite.nunique() == 1:
        return [{"bin": f"{safe_float(finite.iloc[0], 2)}", "count": int(len(finite))}]
    try:
        counts, edges = np.histogram(finite, bins=min(bins, max(finite.nunique(), 2)))
    except (ValueError, MemoryError):
        return []
    return [
        {"bin": f"{edges[i]:.2f} - {edges[i + 1]:.2f}", "count": int(counts[i])}
        for i in range(len(counts))
    ]


# ---------------------------------------------------------------------------
# Quality scores
# ---------------------------------------------------------------------------


def _completeness_score(df: pd.DataFrame) -> float:
    total_cells = df.shape[0] * df.shape[1]
    if total_cells == 0:
        return 0.0
    non_null = int(total_cells - df.isna().sum().sum())
    return round(non_null / total_cells * 100, 1)


def _uniqueness_score(df: pd.DataFrame) -> float:
    """Share of columns carrying usable variation.

    An earlier version averaged each column's distinct-value ratio. That was a
    bad measure of quality: a `region` column with four values is *correct*, but
    scored 3%, which dragged a pristine dataset's overall score down for no real
    defect. What actually harms a dataset is degenerate columns - constant, or
    so dominated by one value that they carry almost no signal. This measures
    exactly that.
    """
    columns = 0
    healthy = 0
    for col in df.columns:
        non_null = df[col].dropna()
        if non_null.empty:
            columns += 1  # a fully empty column is a real defect
            continue
        columns += 1
        distinct = non_null.nunique()
        if distinct <= 1:
            continue  # constant
        dominant_share = float(non_null.value_counts().iloc[0]) / len(non_null)
        if dominant_share >= NEAR_CONSTANT_RATIO:
            continue  # over 95% one value
        healthy += 1
    if columns == 0:
        return 100.0
    return round(healthy / columns * 100, 1)


def _duplicate_score(df: pd.DataFrame) -> tuple[float, int]:
    rows = len(df)
    if rows == 0:
        return 100.0, 0
    duplicates = int(df.duplicated().sum())
    return round((1 - duplicates / rows) * 100, 1), duplicates


def _consistency_score(df: pd.DataFrame) -> float:
    shares = []
    for col in df.columns:
        non_null = df[col].dropna()
        if non_null.empty:
            continue
        if not (
            pd.api.types.is_object_dtype(non_null)
            or pd.api.types.is_string_dtype(non_null)
        ):
            shares.append(1.0)
            continue
        sample = non_null.head(1000)
        numeric_share = float(pd.to_numeric(sample, errors="coerce").notna().mean())
        try:
            date_share = float(
                pd.to_datetime(sample, errors="coerce", format="mixed").notna().mean()
            )
        except (ValueError, TypeError):
            date_share = 0.0
        text_share = 1.0 - max(numeric_share, date_share)
        shares.append(max(numeric_share, date_share, text_share))
    return round(float(np.mean(shares)) * 100, 1) if shares else 100.0


def compute_quality_scores(df: pd.DataFrame) -> dict[str, Any]:
    completeness = _completeness_score(df)
    uniqueness = _uniqueness_score(df)
    duplicates, duplicate_rows = _duplicate_score(df)
    consistency = _consistency_score(df)

    overall = (
        completeness * SCORE_WEIGHTS["completeness"]
        + duplicates * SCORE_WEIGHTS["duplicates"]
        + consistency * SCORE_WEIGHTS["consistency"]
        + uniqueness * SCORE_WEIGHTS["uniqueness"]
    )
    return {
        "overall_score": round(overall, 1),
        "completeness_score": completeness,
        "uniqueness_score": uniqueness,
        "duplicate_score": duplicates,
        "consistency_score": consistency,
        "duplicate_rows": duplicate_rows,
        "weights": SCORE_WEIGHTS,
        "score_definitions": SCORE_DEFINITIONS,
    }


def grade_for(score: float) -> str:
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "good"
    if score >= 60:
        return "fair"
    return "poor"


# ---------------------------------------------------------------------------
# Correlations
# ---------------------------------------------------------------------------


def compute_correlations(
    df: pd.DataFrame, max_columns: int | None = None
) -> dict[str, Any]:
    max_columns = max_columns or settings.MAX_CORRELATION_COLUMNS
    numeric = df.select_dtypes(include=[np.number])
    # Constant columns yield NaN correlations, so drop them up front.
    if not numeric.empty:
        numeric = numeric.loc[:, numeric.std(numeric_only=True).fillna(0) > 0]

    if numeric.shape[1] < 2:
        return {"columns": [], "matrix": [], "top_pairs": [], "truncated": False}

    truncated = numeric.shape[1] > max_columns
    if truncated:
        # Keep the highest-variance columns - those carry the most signal.
        keep = (
            numeric.var(numeric_only=True)
            .sort_values(ascending=False)
            .head(max_columns)
            .index
        )
        numeric = numeric[keep]

    corr = numeric.corr(numeric_only=True)
    columns = [str(c) for c in corr.columns]
    matrix = [
        [safe_float(corr.iloc[i, j], 3) for j in range(len(columns))]
        for i in range(len(columns))
    ]

    pairs = []
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            value = safe_float(corr.iloc[i, j], 3)
            if value is None:
                continue
            pairs.append({"x": columns[i], "y": columns[j], "correlation": value})
    pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)

    return {
        "columns": columns,
        "matrix": matrix,
        "top_pairs": pairs[:12],
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Warnings + recommendations
# ---------------------------------------------------------------------------


def build_warnings(
    df: pd.DataFrame, column_profiles: list[dict[str, Any]], scores: dict[str, Any]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(severity: str, code: str, message: str, columns: list[str] | None = None):
        out.append(
            {
                "severity": severity,
                "code": code,
                "message": message,
                "columns": columns or [],
            }
        )

    if scores["duplicate_rows"] > 0:
        pct = scores["duplicate_rows"] / max(len(df), 1) * 100
        add(
            "warning" if pct < 10 else "danger",
            "duplicate_rows",
            f"{scores['duplicate_rows']} duplicate rows ({pct:.1f}% of the dataset).",
        )

    high_missing = [
        c["column"] for c in column_profiles if (c["missing_pct"] or 0) >= 40
    ]
    if high_missing:
        add(
            "danger",
            "high_missing",
            f"{len(high_missing)} column(s) are at least 40% empty.",
            high_missing,
        )

    some_missing = [
        c["column"] for c in column_profiles if 0 < (c["missing_pct"] or 0) < 40
    ]
    if some_missing:
        add(
            "warning",
            "some_missing",
            f"{len(some_missing)} column(s) have some missing values.",
            some_missing,
        )

    constant = [c["column"] for c in column_profiles if c["is_constant"]]
    if constant:
        add(
            "warning",
            "constant_columns",
            f"{len(constant)} column(s) hold a single value and carry no signal.",
            constant,
        )

    near_constant = [
        c["column"]
        for c in column_profiles
        if not c["is_constant"]
        and c["top_values"]
        and (c["top_values"][0]["pct"] or 0) >= NEAR_CONSTANT_RATIO * 100
    ]
    if near_constant:
        add(
            "info",
            "near_constant_columns",
            f"{len(near_constant)} column(s) are over 95% a single value.",
            near_constant,
        )

    high_cardinality = [
        c["column"]
        for c in column_profiles
        if c["semantic_type"] in ("categorical", "text")
        and (c["unique_pct"] or 0) > HIGH_CARDINALITY_RATIO * 100
    ]
    if high_cardinality:
        add(
            "info",
            "high_cardinality",
            f"{len(high_cardinality)} text column(s) are near-unique per row.",
            high_cardinality,
        )

    # Continuous columns are excluded: a float measurement is unique on nearly
    # every row by nature, and flagging it as an identifier would tell the user
    # to drop the very column they most likely want to predict.
    identifiers = [
        c["column"]
        for c in column_profiles
        if (c["unique_pct"] or 0) >= 99.9
        and c["non_null_count"] > 10
        and not is_continuous(df[c["column"]])
    ]
    if identifiers:
        add(
            "info",
            "identifier_columns",
            f"{len(identifiers)} likely identifier column(s) - exclude these from training.",
            identifiers,
        )

    outlier_cols = [
        c["column"] for c in column_profiles if (c["outlier_count"] or 0) > 0
    ]
    if outlier_cols:
        total = sum(c["outlier_count"] or 0 for c in column_profiles)
        add(
            "info",
            "outliers",
            f"{total} outlier value(s) across {len(outlier_cols)} numeric column(s), by the 1.5xIQR rule.",
            outlier_cols,
        )

    if scores["consistency_score"] < 85:
        add(
            "warning",
            "mixed_types",
            f"Type consistency is {scores['consistency_score']}% - some text columns mix numbers, dates, and text.",
        )

    return out


def build_recommendations(
    warnings_list: list[dict[str, Any]], scores: dict[str, Any]
) -> list[dict[str, Any]]:
    """Concrete next actions, each tied to a warning that actually triggered."""
    codes = {w["code"] for w in warnings_list}
    recs: list[dict[str, Any]] = []

    if "duplicate_rows" in codes:
        recs.append(
            {
                "action": "Remove duplicate rows",
                "where": "Data Quality",
                "why": "Duplicates bias every aggregate and inflate model scores.",
            }
        )
    if "high_missing" in codes:
        recs.append(
            {
                "action": "Drop or impute the mostly-empty columns",
                "where": "Data Quality",
                "why": "Columns over 40% empty rarely help a model and can mislead imputation.",
            }
        )
    if "some_missing" in codes:
        recs.append(
            {
                "action": "Choose a missing-value strategy",
                "where": "Data Quality",
                "why": "Explicit imputation beats letting each tool decide for itself.",
            }
        )
    if "constant_columns" in codes:
        recs.append(
            {
                "action": "Exclude constant columns from training",
                "where": "Models",
                "why": "A column with one value cannot explain variation in the target.",
            }
        )
    if "identifier_columns" in codes:
        recs.append(
            {
                "action": "Exclude identifier columns from training",
                "where": "Models",
                "why": "Row IDs leak row identity and produce unrealistically high scores.",
            }
        )
    if "mixed_types" in codes:
        recs.append(
            {
                "action": "Parse dates and coerce numeric text columns",
                "where": "Data Quality",
                "why": "Mixed-type columns get treated as unordered text, losing their meaning.",
            }
        )
    if "outliers" in codes:
        recs.append(
            {
                "action": "Review outliers before capping them",
                "where": "Data Explorer",
                "why": "Outliers are sometimes the most important rows, not errors.",
            }
        )

    if scores["overall_score"] >= 90 and not recs:
        recs.append(
            {
                "action": "Train a model",
                "where": "Models",
                "why": "Data quality is already high enough to model directly.",
            }
        )
    return recs


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def profile_dataframe(df: pd.DataFrame, size_bytes: int) -> dict[str, Any]:
    """The original flat profile shape, preserved so existing consumers of
    `GET /datasets/{id}/profile` keep working unchanged."""
    rows, cols = df.shape
    numeric_cols = detect_numeric_columns(df)
    bool_cols = [str(c) for c in df.select_dtypes(include=["bool"]).columns]
    date_cols = detect_datetime_columns(df)
    categorical_cols = [
        str(c)
        for c in df.columns
        if str(c) not in numeric_cols
        and str(c) not in bool_cols
        and str(c) not in date_cols
    ]

    total_cells = rows * cols
    missing_pct = (
        round(float(df.isna().sum().sum()) / total_cells * 100, 2)
        if total_cells
        else 0.0
    )
    duplicate_pct = round(float(df.duplicated().sum()) / rows * 100, 2) if rows else 0.0

    outlier_count = 0
    for c in numeric_cols:
        outlier_count += iqr_outlier_count(
            pd.to_numeric(df[c], errors="coerce").dropna()
        )

    target_col, confidence = guess_target_column(df)
    return {
        "rows": int(rows),
        "columns": int(cols),
        "numeric_columns": len(numeric_cols),
        "categorical_columns": len(categorical_cols),
        "date_columns": len(date_cols),
        "boolean_columns": len(bool_cols),
        "memory_usage_mb": round(size_bytes / (1024 * 1024), 2),
        "missing_values_pct": missing_pct,
        "duplicates_pct": duplicate_pct,
        "outliers_found": int(outlier_count),
        "recommended_target_column": target_col,
        "target_confidence_pct": round(confidence * 100, 1),
    }


class ProfilingService:
    """Full data-quality report: scores, per-column profiles, correlations,
    warnings, and recommended actions."""

    def full_profile(
        self,
        df: pd.DataFrame,
        size_bytes: int,
        source: str = "original",
        sampled: bool = False,
        total_rows: int | None = None,
    ) -> dict[str, Any]:
        column_profiles = [profile_column(df, c) for c in df.columns]
        scores = compute_quality_scores(df)
        warnings_list = build_warnings(df, column_profiles, scores)
        recommendations = build_recommendations(warnings_list, scores)

        type_counts: dict[str, int] = {}
        for prof in column_profiles:
            type_counts[prof["semantic_type"]] = (
                type_counts.get(prof["semantic_type"], 0) + 1
            )

        numeric_summary = [
            {
                "column": p["column"],
                "min": p["min"],
                "max": p["max"],
                "mean": p["mean"],
                "median": p["median"],
                "std": p["std"],
                "missing_pct": p["missing_pct"],
                "outlier_count": p["outlier_count"],
            }
            for p in column_profiles
            if p["semantic_type"] == "numeric"
        ]
        categorical_summary = [
            {
                "column": p["column"],
                "unique_count": p["unique_count"],
                "missing_pct": p["missing_pct"],
                "top_values": p["top_values"][:5],
            }
            for p in column_profiles
            if p["semantic_type"] in ("categorical", "boolean", "text")
        ]

        return to_jsonable(
            {
                "summary": {
                    **profile_dataframe(df, size_bytes),
                    "data_source": source,
                    "sampled": sampled,
                    "rows_in_file": total_rows
                    if total_rows is not None
                    else int(len(df)),
                    "rows_analysed": int(len(df)),
                },
                "quality": {**scores, "grade": grade_for(scores["overall_score"])},
                "column_type_distribution": [
                    {"type": k, "count": v} for k, v in sorted(type_counts.items())
                ],
                "missing_by_column": [
                    {
                        "column": p["column"],
                        "missing_count": p["missing_count"],
                        "missing_pct": p["missing_pct"],
                    }
                    for p in sorted(
                        column_profiles,
                        key=lambda x: x["missing_pct"] or 0,
                        reverse=True,
                    )
                    if (p["missing_pct"] or 0) > 0
                ],
                "outliers_by_column": [
                    {"column": p["column"], "outlier_count": p["outlier_count"]}
                    for p in column_profiles
                    if (p["outlier_count"] or 0) > 0
                ],
                "numeric_summary": numeric_summary,
                "categorical_summary": categorical_summary,
                "correlations": compute_correlations(df),
                "target_candidates": recommend_targets(df),
                "warnings": warnings_list,
                "recommendations": recommendations,
                "data_dictionary": [
                    {
                        "column": p["column"],
                        "dtype": p["dtype"],
                        "semantic_type": p["semantic_type"],
                        "non_null_count": p["non_null_count"],
                        "missing_pct": p["missing_pct"],
                        "unique_count": p["unique_count"],
                        "example_values": p["example_values"],
                    }
                    for p in column_profiles
                ],
            }
        )

    def column_profile(self, df: pd.DataFrame, column: str) -> dict[str, Any]:
        return to_jsonable(profile_column(df, column))

    def columns_overview(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        """Lightweight per-column metadata for table headers and pickers -
        deliberately cheaper than a full profile."""
        out = []
        for col in df.columns:
            series = df[col]
            total = int(len(series))
            non_null = int(series.notna().sum())
            out.append(
                {
                    "column": str(col),
                    "dtype": str(series.dtype),
                    "semantic_type": infer_semantic_type(series),
                    "non_null_count": non_null,
                    "missing_count": total - non_null,
                    "missing_pct": safe_float((total - non_null) / total * 100, 2)
                    if total
                    else 0.0,
                    "unique_count": safe_int(series.dropna().nunique()) or 0,
                }
            )
        return to_jsonable(out)


profiling_service = ProfilingService()
