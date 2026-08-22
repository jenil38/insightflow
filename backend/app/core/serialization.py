"""
Safe JSON serialization for pandas/NumPy values.

FastAPI's default encoder raises on NumPy scalars and emits invalid JSON
(`NaN`, `Infinity`) for float edge cases, which then breaks `JSON.parse` in the
browser. Every endpoint that returns values derived from a DataFrame routes
them through `to_jsonable` first.

Rules:
- NaN / NaT / None / +-inf -> None (JSON null)
- NumPy integer/float/bool  -> Python int/float/bool
- Timestamps / dates        -> ISO 8601 strings
- Anything unrecognised     -> str(value), so we degrade rather than 500
"""

from __future__ import annotations

import datetime as _dt
import math
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        # pd.isna returns an array for list-likes, which is not what we want here.
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, (bool, np.bool_)) else False


def to_jsonable(value: Any) -> Any:
    """Recursively convert `value` into something json.dumps can handle."""
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, pd.Series):
        return [to_jsonable(v) for v in value.tolist()]

    if _is_missing(value):
        return None

    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating, Decimal)):
        as_float = float(value)
        if math.isnan(as_float) or math.isinf(as_float):
            return None
        return as_float
    if isinstance(value, (pd.Timestamp, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    return str(value)


def safe_float(value: Any, digits: int | None = 4) -> float | None:
    """Single-scalar helper: returns a finite rounded float, or None."""
    if _is_missing(value):
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(as_float) or math.isinf(as_float):
        return None
    return round(as_float, digits) if digits is not None else as_float


def safe_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(as_float) or math.isinf(as_float):
        return None
    return int(as_float)


def dataframe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> list of JSON-safe row dicts, preserving column order."""
    columns = [str(c) for c in df.columns]
    records: list[dict[str, Any]] = []
    for row in df.itertuples(index=False, name=None):
        records.append({col: to_jsonable(val) for col, val in zip(columns, row)})
    return records
