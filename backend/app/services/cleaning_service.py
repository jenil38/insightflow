"""
Configurable, previewable, reversible data cleaning.

The original implementation applied a fixed pipeline and, notably, lower-cased
every text value without telling the user. Here every transformation is opt-in
via `CleaningConfig`, the same code path can run in "preview" mode (compute the
effects, write nothing), and applying cleaning never touches the original
upload - it writes a separate file that can be discarded to revert.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..core.serialization import dataframe_records, to_jsonable
from ..schemas import CleaningConfig
from .profiling_service import infer_semantic_type


class CleaningService:
    # ----------------------------------------------------------------- plan
    def recommend_config(self, df: pd.DataFrame) -> dict[str, Any]:
        """Build a suggested plan from what the data actually needs, so the UI
        can pre-tick only the relevant boxes and explain why."""
        reasons: list[str] = []
        config = CleaningConfig()

        duplicates = int(df.duplicated().sum())
        config.remove_duplicates = duplicates > 0
        if duplicates:
            reasons.append(f"{duplicates} duplicate row(s) found.")

        text_cols = [c for c in df.columns if pd.api.types.is_object_dtype(df[c])]
        needs_trim = False
        for c in text_cols:
            values = df[c].dropna().astype(str)
            if not values.empty and values.str.strip().ne(values).any():
                needs_trim = True
                break
        config.trim_whitespace = needs_trim
        if needs_trim:
            reasons.append("Some text values have leading or trailing whitespace.")

        date_like = [c for c in text_cols if infer_semantic_type(df[c]) == "datetime"]
        config.parse_dates = bool(date_like)
        if date_like:
            preview = ", ".join(str(c) for c in date_like[:3])
            reasons.append(
                f"{len(date_like)} text column(s) look like dates: {preview}."
            )

        numeric_missing = int(df.select_dtypes(include=[np.number]).isna().sum().sum())
        config.numeric_missing_strategy = "median" if numeric_missing else "leave"
        if numeric_missing:
            reasons.append(
                f"{numeric_missing} missing numeric value(s); median imputation suggested."
            )

        cat_missing = int(sum(int(df[c].isna().sum()) for c in text_cols))
        config.categorical_missing_strategy = "mode" if cat_missing else "leave"
        if cat_missing:
            reasons.append(
                f"{cat_missing} missing text value(s); most-frequent imputation suggested."
            )

        # Case standardisation is never auto-suggested: it is lossy, so the user
        # should opt in knowingly.
        config.standardize_case = "none"
        config.outlier_strategy = "report"

        return {
            "recommended_config": config.model_dump(),
            "reasons": reasons
            or ["No cleaning issues detected - this dataset already looks tidy."],
        }

    # -------------------------------------------------------------- execute
    def apply_config(
        self, df: pd.DataFrame, config: CleaningConfig
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Run the configured pipeline. Returns (cleaned_df, report).

        The report records rows/values/columns affected per step, so the UI can
        show a truthful before/after including for destructive options.
        """
        original_rows, original_cols = df.shape
        original_missing = int(df.isna().sum().sum())
        original_duplicates = int(df.duplicated().sum())
        work = df.copy()
        steps: list[dict[str, Any]] = []

        # --- duplicates -------------------------------------------------
        if config.remove_duplicates:
            before = len(work)
            work = work.drop_duplicates().reset_index(drop=True)
            removed = before - len(work)
            steps.append(
                self._step(
                    "Remove duplicate rows",
                    rows=removed,
                    detail=f"Dropped {removed} exact duplicate row(s).",
                )
            )

        text_cols = [c for c in work.columns if pd.api.types.is_object_dtype(work[c])]
        date_cols = (
            [c for c in text_cols if infer_semantic_type(work[c]) == "datetime"]
            if config.parse_dates
            else []
        )
        pure_text_cols = [c for c in text_cols if c not in date_cols]

        # --- whitespace -------------------------------------------------
        if config.trim_whitespace and pure_text_cols:
            changed, touched = self._transform_text(
                work, pure_text_cols, lambda s: s.str.strip()
            )
            steps.append(
                self._step(
                    "Trim whitespace",
                    values=changed,
                    columns=touched,
                    detail=f"Trimmed {changed} value(s) across {len(touched)} column(s).",
                )
            )

        if config.normalize_whitespace and pure_text_cols:
            changed, touched = self._transform_text(
                work, pure_text_cols, lambda s: s.str.replace(r"\s+", " ", regex=True)
            )
            steps.append(
                self._step(
                    "Collapse repeated whitespace",
                    values=changed,
                    columns=touched,
                    detail=f"Normalised spacing in {changed} value(s).",
                )
            )

        # --- case (explicit opt-in only) --------------------------------
        if config.standardize_case != "none" and pure_text_cols:
            transform = {
                "lower": lambda s: s.str.lower(),
                "upper": lambda s: s.str.upper(),
                "title": lambda s: s.str.title(),
            }[config.standardize_case]
            changed, touched = self._transform_text(work, pure_text_cols, transform)
            steps.append(
                self._step(
                    f"Standardise text case ({config.standardize_case})",
                    values=changed,
                    columns=touched,
                    detail=(
                        f"Rewrote {changed} value(s) to {config.standardize_case}case. This is lossy - "
                        "the original capitalisation is only recoverable by reverting to the original data."
                    ),
                )
            )

        # --- dates ------------------------------------------------------
        if date_cols:
            parsed_total = 0
            failed_total = 0
            for col in date_cols:
                before_valid = int(work[col].notna().sum())
                parsed = pd.to_datetime(work[col], errors="coerce", format="mixed")
                after_valid = int(parsed.notna().sum())
                formatted = parsed.dt.strftime("%Y-%m-%d")
                work[col] = formatted.where(parsed.notna(), np.nan)
                parsed_total += after_valid
                failed_total += max(0, before_valid - after_valid)
            steps.append(
                self._step(
                    "Parse date columns",
                    values=parsed_total,
                    columns=[str(c) for c in date_cols],
                    detail=(
                        f"Parsed {parsed_total} value(s) to YYYY-MM-DD across {len(date_cols)} column(s)."
                        + (
                            f" {failed_total} value(s) could not be parsed and became empty."
                            if failed_total
                            else ""
                        )
                    ),
                )
            )

        # --- numeric missing --------------------------------------------
        numeric_cols = work.select_dtypes(include=[np.number]).columns.tolist()
        if config.numeric_missing_strategy != "leave" and numeric_cols:
            filled, touched, rows_to_drop = self._fill_missing(
                work, numeric_cols, config.numeric_missing_strategy, numeric=True
            )
            if rows_to_drop:
                work = work.dropna(subset=numeric_cols).reset_index(drop=True)
            steps.append(
                self._step(
                    f"Handle missing numeric values ({config.numeric_missing_strategy})",
                    rows=rows_to_drop,
                    values=filled,
                    columns=touched,
                    detail=(
                        f"Dropped {rows_to_drop} row(s) with missing numeric values."
                        if config.numeric_missing_strategy == "drop"
                        else f"Filled {filled} missing value(s) across {len(touched)} column(s)."
                    ),
                )
            )

        # --- categorical missing ----------------------------------------
        cat_cols = [c for c in work.columns if pd.api.types.is_object_dtype(work[c])]
        if config.categorical_missing_strategy != "leave" and cat_cols:
            filled, touched, rows_to_drop = self._fill_missing(
                work, cat_cols, config.categorical_missing_strategy, numeric=False
            )
            if rows_to_drop:
                work = work.dropna(subset=cat_cols).reset_index(drop=True)
            steps.append(
                self._step(
                    f"Handle missing text values ({config.categorical_missing_strategy})",
                    rows=rows_to_drop,
                    values=filled,
                    columns=touched,
                    detail=(
                        f"Dropped {rows_to_drop} row(s) with missing text values."
                        if config.categorical_missing_strategy == "drop"
                        else f"Filled {filled} missing value(s) across {len(touched)} column(s)."
                    ),
                )
            )

        # --- outliers ---------------------------------------------------
        outlier_step = self._handle_outliers(work, config.outlier_strategy)
        if outlier_step:
            work = outlier_step.pop("_frame")
            steps.append(outlier_step)

        # --- drop empty columns -----------------------------------------
        if config.drop_empty_columns:
            empty = [str(c) for c in work.columns if work[c].isna().all()]
            if empty:
                work = work.drop(columns=empty)
            steps.append(
                self._step(
                    "Drop fully empty columns",
                    columns=empty,
                    detail=f"Dropped {len(empty)} column(s) containing no values.",
                )
            )

        # A report full of "0 rows / 0 values affected" lines is noise, not
        # information, so only steps that actually did something are reported.
        # `always_report` steps are informational by design and always kept.
        always_report = ("Detect outliers",)
        steps = [
            s
            for s in steps
            if s["rows_affected"]
            or s["values_affected"]
            or s["columns_affected"]
            or s["step"].startswith(always_report)
        ]

        final_missing = int(work.isna().sum().sum())
        report = {
            "steps": steps,
            "before": {
                "rows": int(original_rows),
                "columns": int(original_cols),
                "missing_values": original_missing,
                "duplicate_rows": original_duplicates,
            },
            "after": {
                "rows": int(work.shape[0]),
                "columns": int(work.shape[1]),
                "missing_values": final_missing,
                "duplicate_rows": int(work.duplicated().sum()),
            },
            "rows_removed": int(original_rows - work.shape[0]),
            "columns_removed": int(original_cols - work.shape[1]),
            "missing_values_filled": int(max(0, original_missing - final_missing)),
            "config_used": config.model_dump(),
            # Legacy keys: the original /clean response shape, so any existing
            # consumer of that endpoint keeps working.
            "duplicates_removed": self._step_value(
                steps, "Remove duplicate", "rows_affected"
            ),
            "dates_corrected": self._step_value(steps, "Parse date", "values_affected"),
            "categories_standardized": self._step_value(
                steps, "Standardise", "values_affected"
            ),
            "text_columns_normalized": len(pure_text_cols),
            "rows_after_cleaning": int(work.shape[0]),
            "columns_after_cleaning": int(work.shape[1]),
        }
        return work, to_jsonable(report)

    # ------------------------------------------------------------- preview
    def preview(
        self, df: pd.DataFrame, config: CleaningConfig, sample_rows: int = 10
    ) -> dict[str, Any]:
        """Compute the full effect of a config without persisting anything."""
        cleaned, report = self.apply_config(df, config)
        report["preview_rows"] = dataframe_records(cleaned.head(sample_rows))
        report["preview_columns"] = [str(c) for c in cleaned.columns]
        report["destructive"] = bool(
            report["rows_removed"] > 0
            or report["columns_removed"] > 0
            or config.standardize_case != "none"
            or config.outlier_strategy in ("cap", "remove")
        )
        return to_jsonable(report)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _step(
        name: str,
        rows: int = 0,
        values: int = 0,
        columns: list[str] | None = None,
        detail: str = "",
    ) -> dict[str, Any]:
        return {
            "step": name,
            "applied": True,
            "rows_affected": int(rows),
            "values_affected": int(values),
            "columns_affected": columns or [],
            "detail": detail,
        }

    @staticmethod
    def _step_value(steps: list[dict[str, Any]], prefix: str, key: str) -> int:
        return next((s[key] for s in steps if s["step"].startswith(prefix)), 0)

    @staticmethod
    def _transform_text(
        df: pd.DataFrame, columns: list, transform
    ) -> tuple[int, list[str]]:
        """Apply a string transform in place; returns (values_changed, columns_touched)."""
        changed_total = 0
        touched: list[str] = []
        for col in columns:
            mask = df[col].notna()
            if not mask.any():
                continue
            current = df.loc[mask, col].astype(str)
            new_values = transform(current)
            differs = int((new_values != current).sum())
            if differs:
                df.loc[mask, col] = new_values
                changed_total += differs
                touched.append(str(col))
        return changed_total, touched

    @staticmethod
    def _fill_missing(
        df: pd.DataFrame, columns: list, strategy: str, numeric: bool
    ) -> tuple[int, list[str], int]:
        """Returns (values_filled, columns_touched, rows_to_drop)."""
        if strategy == "drop":
            rows_with_missing = int(df[columns].isna().any(axis=1).sum())
            return 0, [str(c) for c in columns], rows_with_missing

        filled_total = 0
        touched: list[str] = []
        for col in columns:
            missing = int(df[col].isna().sum())
            if not missing:
                continue
            if numeric:
                series = pd.to_numeric(df[col], errors="coerce")
                value = {
                    "median": series.median(),
                    "mean": series.mean(),
                    "zero": 0,
                }[strategy]
                if pd.isna(value):
                    continue
            else:
                if strategy == "mode":
                    mode = df[col].mode(dropna=True)
                    value = mode.iloc[0] if not mode.empty else "Unknown"
                else:  # "unknown"
                    value = "Unknown"
            df[col] = df[col].fillna(value)
            filled_total += missing
            touched.append(str(col))
        return filled_total, touched, 0

    @staticmethod
    def _handle_outliers(df: pd.DataFrame, strategy: str) -> dict[str, Any] | None:
        if strategy == "leave":
            return None

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if not numeric_cols:
            return None

        bounds: dict[Any, tuple[float, float]] = {}
        counts: dict[Any, int] = {}
        for col in numeric_cols:
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(series) < 4:
                continue
            q1, q3 = series.quantile(0.25), series.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0 or pd.isna(iqr):
                continue
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            count = int(((series < lower) | (series > upper)).sum())
            if count:
                bounds[col] = (float(lower), float(upper))
                counts[col] = count

        total = sum(counts.values())
        affected = [str(c) for c in counts]

        if strategy == "report" or not bounds:
            return {
                **CleaningService._step(
                    "Detect outliers (report only)",
                    columns=affected,
                    detail=(
                        f"Found {total} outlier value(s) across {len(affected)} column(s) by the "
                        "1.5xIQR rule. No values were changed."
                    ),
                ),
                "_frame": df,
            }

        if strategy == "cap":
            for col, (lower, upper) in bounds.items():
                df[col] = pd.to_numeric(df[col], errors="coerce").clip(
                    lower=lower, upper=upper
                )
            return {
                **CleaningService._step(
                    "Cap outliers to IQR bounds",
                    values=total,
                    columns=affected,
                    detail=f"Clipped {total} value(s) into the 1.5xIQR range across {len(affected)} column(s).",
                ),
                "_frame": df,
            }

        # strategy == "remove"
        mask = pd.Series(False, index=df.index)
        for col, (lower, upper) in bounds.items():
            series = pd.to_numeric(df[col], errors="coerce")
            mask |= (series < lower) | (series > upper)
        removed = int(mask.sum())
        return {
            **CleaningService._step(
                "Remove outlier rows",
                rows=removed,
                columns=affected,
                detail=f"Dropped {removed} row(s) containing at least one 1.5xIQR outlier.",
            ),
            "_frame": df.loc[~mask].reset_index(drop=True),
        }


cleaning_service = CleaningService()


def clean_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Backward-compatible wrapper matching the original `clean_dataframe`.

    Uses the original default behaviour (dedupe, trim, parse dates, median /
    mode imputation) but no longer silently lower-cases text - that was a
    data-loss bug, so `standardize_case` stays off unless explicitly requested.
    """
    return cleaning_service.apply_config(df, CleaningConfig())
