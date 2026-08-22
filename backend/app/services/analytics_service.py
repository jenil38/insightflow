"""
Analytics: the auto-generated dashboard, plus a configurable query engine.

`auto_dashboard` preserves the original `/dashboard` response shape so existing
consumers keep working. `run_query` is the new configurable path behind the
chart builder - the user chooses measure, aggregation, dimension, date column,
time grain, top-N and chart type, and the server validates that the combination
is statistically sensible before computing it.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..core.exceptions import ValidationAppError
from ..core.serialization import safe_float, to_jsonable
from ..schemas import AnalyticsQuery
from .profiling_service import (
    detect_datetime_columns, guess_target_column, infer_semantic_type, numeric_histogram,
)

GRAIN_FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}

# A pie chart stops communicating anything past a handful of slices.
MAX_PIE_SLICES = 8


def safe_num(x) -> float | None:
    """Preserved from the original module (imported by report generation)."""
    return safe_float(x, 2)


class AnalyticsService:
    # ------------------------------------------------------- auto dashboard
    def auto_dashboard(self, df: pd.DataFrame) -> dict[str, Any]:
        """The original automatic dashboard: KPIs, a time series, a category
        breakdown and a histogram, chosen heuristically."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        date_cols = detect_datetime_columns(df)
        date_col = date_cols[0] if date_cols else None

        target_col, _ = guess_target_column(df)
        categorical_cols = [
            c for c in df.columns
            if infer_semantic_type(df[c]) in ("categorical", "boolean") and c != date_col
        ]

        kpis: list[dict[str, Any]] = []
        if target_col and target_col in numeric_cols:
            series = pd.to_numeric(df[target_col], errors="coerce").dropna()
            if not series.empty:
                kpis += [
                    {"label": f"Total {target_col}", "value": safe_num(series.sum())},
                    {"label": f"Average {target_col}", "value": safe_num(series.mean())},
                    {"label": f"Max {target_col}", "value": safe_num(series.max())},
                ]
        kpis = [k for k in kpis if k["value"] is not None]
        kpis.append({"label": "Total Rows", "value": int(df.shape[0])})

        time_series: list[dict[str, Any]] = []
        if date_col and target_col and target_col in numeric_cols:
            time_series = self._time_series(df, date_col, target_col, "sum", "month")[:24]

        category_breakdown: list[dict[str, Any]] = []
        category_column = categorical_cols[0] if categorical_cols else None
        if category_column:
            counts = df[category_column].value_counts().head(10)
            category_breakdown = [
                {"category": str(k), "count": int(v)} for k, v in counts.items()
            ]

        histogram: list[dict[str, Any]] = []
        if target_col and target_col in numeric_cols:
            series = pd.to_numeric(df[target_col], errors="coerce").dropna()
            if not series.empty:
                histogram = [
                    {"bin": h["bin"], "count": h["count"]} for h in numeric_histogram(series, bins=10)
                ]

        return to_jsonable({
            "kpis": kpis,
            "target_column": target_col,
            "date_column": date_col,
            "category_column": category_column,
            "time_series": time_series,
            "category_breakdown": category_breakdown,
            "histogram": histogram,
            "available": {
                "numeric_columns": [str(c) for c in numeric_cols],
                "categorical_columns": [str(c) for c in categorical_cols],
                "date_columns": [str(c) for c in date_cols],
            },
            "insights": self._insights(df, target_col, category_column, date_col),
        })

    # ------------------------------------------------------------- queries
    def run_query(self, df: pd.DataFrame, query: AnalyticsQuery) -> dict[str, Any]:
        """Execute a user-configured chart query, validating the combination."""
        self._validate(df, query)

        if query.chart_type == "kpi":
            return self._kpi(df, query)
        if query.chart_type == "histogram":
            return self._histogram(df, query)
        if query.chart_type == "scatter":
            return self._scatter(df, query)
        if query.chart_type in ("line", "area") or query.date_column:
            return self._timeseries_result(df, query)
        return self._grouped(df, query)

    def _validate(self, df: pd.DataFrame, query: AnalyticsQuery) -> None:
        for field, value in (
            ("measure", query.measure),
            ("dimension", query.dimension),
            ("date_column", query.date_column),
            ("secondary_measure", query.secondary_measure),
        ):
            if value is not None and value not in df.columns:
                raise ValidationAppError(
                    f"Column '{value}' (used as {field}) is not in this dataset.",
                    error_code="unknown_column",
                    status_code=400,
                )

        # Every aggregation except count needs something numeric to aggregate.
        if query.aggregation != "count":
            if not query.measure:
                raise ValidationAppError(
                    f"A measure column is required for the '{query.aggregation}' aggregation.",
                    error_code="measure_required",
                    status_code=400,
                )
            if not pd.api.types.is_numeric_dtype(df[query.measure]):
                raise ValidationAppError(
                    f"Column '{query.measure}' is not numeric, so it cannot be aggregated with "
                    f"'{query.aggregation}'. Use 'count', or pick a numeric column.",
                    error_code="measure_not_numeric",
                    status_code=400,
                )

        if query.chart_type in ("line", "area") and not query.date_column:
            raise ValidationAppError(
                "Line and area charts need a date column to plot against.",
                error_code="date_column_required",
                status_code=400,
            )

        if query.chart_type == "scatter":
            if not query.measure or not query.secondary_measure:
                raise ValidationAppError(
                    "A scatter plot needs two numeric columns.",
                    error_code="two_measures_required",
                    status_code=400,
                )

        if query.chart_type == "histogram" and not query.measure:
            raise ValidationAppError(
                "A histogram needs one numeric column.",
                error_code="measure_required",
                status_code=400,
            )

        if query.chart_type == "pie" and query.dimension:
            distinct = int(df[query.dimension].dropna().nunique())
            if distinct > MAX_PIE_SLICES:
                raise ValidationAppError(
                    f"'{query.dimension}' has {distinct} distinct values. A pie chart is only "
                    f"readable up to {MAX_PIE_SLICES} - use a bar chart instead.",
                    error_code="too_many_slices",
                    status_code=400,
                )

    @staticmethod
    def _aggregate(series: pd.Series, aggregation: str) -> float | None:
        if aggregation == "count":
            return safe_float(series.notna().sum(), 2)
        numeric = pd.to_numeric(series, errors="coerce")
        func = {
            "sum": numeric.sum, "avg": numeric.mean, "min": numeric.min,
            "max": numeric.max, "median": numeric.median,
        }[aggregation]
        return safe_float(func(), 2)

    def _kpi(self, df: pd.DataFrame, query: AnalyticsQuery) -> dict[str, Any]:
        column = query.measure or df.columns[0]
        value = self._aggregate(df[column], query.aggregation)
        return to_jsonable({
            "chart_type": "kpi",
            "label": f"{query.aggregation.title()} of {column}" if query.aggregation != "count" else f"Count of {column}",
            "value": value,
            "rows_considered": int(len(df)),
        })

    def _histogram(self, df: pd.DataFrame, query: AnalyticsQuery) -> dict[str, Any]:
        series = pd.to_numeric(df[query.measure], errors="coerce").dropna()
        return to_jsonable({
            "chart_type": "histogram",
            "measure": query.measure,
            "data": numeric_histogram(series, bins=min(query.top_n, 30)),
            "rows_considered": int(len(series)),
        })

    def _scatter(self, df: pd.DataFrame, query: AnalyticsQuery) -> dict[str, Any]:
        pair = df[[query.measure, query.secondary_measure]].apply(
            pd.to_numeric, errors="coerce"
        ).dropna()
        # Downsample: a scatter of 100k points is unreadable and slow to render.
        limit = 2000
        sampled = len(pair) > limit
        if sampled:
            pair = pair.sample(limit, random_state=42)
        correlation = None
        if len(pair) >= 3:
            correlation = safe_float(pair[query.measure].corr(pair[query.secondary_measure]), 3)
        return to_jsonable({
            "chart_type": "scatter",
            "x": query.measure,
            "y": query.secondary_measure,
            "data": [
                {"x": safe_float(a, 4), "y": safe_float(b, 4)}
                for a, b in zip(pair[query.measure], pair[query.secondary_measure])
            ],
            "correlation": correlation,
            "sampled": sampled,
            "rows_considered": int(len(pair)),
        })

    def _time_series(
        self, df: pd.DataFrame, date_column: str, measure: str | None, aggregation: str, grain: str
    ) -> list[dict[str, Any]]:
        columns = [date_column] + ([measure] if measure and measure != date_column else [])
        work = df[columns].copy()
        work[date_column] = pd.to_datetime(work[date_column], errors="coerce", format="mixed")
        work = work.dropna(subset=[date_column]).sort_values(date_column)
        if work.empty:
            return []

        periods = work[date_column].dt.to_period(GRAIN_FREQ[grain])
        if aggregation == "count" or not measure:
            grouped = work.groupby(periods).size()
        else:
            numeric = pd.to_numeric(work[measure], errors="coerce")
            grouped = numeric.groupby(periods).agg(
                {"sum": "sum", "avg": "mean", "min": "min", "max": "max", "median": "median"}[aggregation]
            )
        out = [
            {"period": str(period), "value": safe_float(value, 2)}
            for period, value in grouped.items()
        ]
        return [row for row in out if row["value"] is not None]

    def _timeseries_result(self, df: pd.DataFrame, query: AnalyticsQuery) -> dict[str, Any]:
        data = self._time_series(
            df, query.date_column, query.measure, query.aggregation, query.time_grain
        )
        return to_jsonable({
            "chart_type": query.chart_type,
            "date_column": query.date_column,
            "measure": query.measure,
            "aggregation": query.aggregation,
            "time_grain": query.time_grain,
            "data": data,
            "points": len(data),
        })

    def _grouped(self, df: pd.DataFrame, query: AnalyticsQuery) -> dict[str, Any]:
        if not query.dimension:
            raise ValidationAppError(
                "A dimension column is required to group by for this chart type.",
                error_code="dimension_required",
                status_code=400,
            )

        if query.aggregation == "count" or not query.measure:
            grouped = df.groupby(df[query.dimension].astype(str)).size()
        else:
            numeric = pd.to_numeric(df[query.measure], errors="coerce")
            grouped = numeric.groupby(df[query.dimension].astype(str)).agg(
                {"sum": "sum", "avg": "mean", "min": "min", "max": "max", "median": "median"}[query.aggregation]
            )

        grouped = grouped.sort_values(ascending=False)
        top = grouped.head(query.top_n)
        rows = [
            {"category": str(k), "value": safe_float(v, 2)}
            for k, v in top.items() if safe_float(v, 2) is not None
        ]
        other_count = max(0, len(grouped) - len(top))
        return to_jsonable({
            "chart_type": query.chart_type,
            "dimension": query.dimension,
            "measure": query.measure,
            "aggregation": query.aggregation,
            "data": rows,
            "categories_shown": len(rows),
            "categories_hidden": other_count,
            "bottom": [
                {"category": str(k), "value": safe_float(v, 2)}
                for k, v in grouped.tail(min(5, len(grouped))).items()
            ],
        })

    # ------------------------------------------------------------ insights
    @staticmethod
    def _insights(
        df: pd.DataFrame, target: str | None, category: str | None, date_col: str | None
    ) -> list[str]:
        """Plain-language observations, each computed rather than asserted."""
        out: list[str] = []
        if target and pd.api.types.is_numeric_dtype(df.get(target, pd.Series(dtype=float))):
            series = pd.to_numeric(df[target], errors="coerce").dropna()
            if not series.empty:
                out.append(
                    f"{target} averages {safe_float(series.mean(), 2)} across {len(series):,} rows, "
                    f"ranging from {safe_float(series.min(), 2)} to {safe_float(series.max(), 2)}."
                )
                if category and category in df.columns:
                    by_cat = pd.to_numeric(df[target], errors="coerce").groupby(
                        df[category].astype(str)
                    ).sum().sort_values(ascending=False)
                    if len(by_cat) >= 2:
                        top_share = by_cat.iloc[0] / by_cat.sum() * 100 if by_cat.sum() else 0
                        out.append(
                            f"{by_cat.index[0]} is the largest {category} by total {target}, "
                            f"accounting for {safe_float(top_share, 1)}% of the total."
                        )
        if date_col:
            parsed = pd.to_datetime(df[date_col], errors="coerce", format="mixed").dropna()
            if not parsed.empty:
                out.append(
                    f"The data spans {parsed.min().date()} to {parsed.max().date()} "
                    f"({(parsed.max() - parsed.min()).days} days)."
                )
        return out


analytics_service = AnalyticsService()


def build_dashboard(df: pd.DataFrame) -> dict[str, Any]:
    """Backward-compatible wrapper for the original `build_dashboard`."""
    return analytics_service.auto_dashboard(df)
