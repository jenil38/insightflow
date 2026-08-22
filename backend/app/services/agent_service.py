"""
Automation agent: runs the full analysis pipeline in one call.

The original version called the `/train` and `/explain` route functions
directly and hard-failed the whole run on the first HTTPException. This version
composes the services, records genuine per-step status (completed / skipped /
failed) with real durations, and continues past a failed step so a dataset that
cannot be modelled still produces profiling, cleaning and analytics results.

Execution is synchronous: the response arrives when the pipeline finishes. The
per-step durations reported are measured, not simulated - the UI shows an honest
"running" state and then the real outcome, rather than a fake progress animation.
"""
from __future__ import annotations

import os
import time
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..core.config import settings
from ..core.exceptions import AppException
from ..core.logging_config import get_logger
from ..core.serialization import to_jsonable
from ..schemas import CleaningConfig, TrainRequest
from .analytics_service import analytics_service
from .cleaning_service import cleaning_service
from .dataframe_io import cleaned_path_for, load_dataset, write_dataframe
from .explainability_service import ExplainabilityService
from .ml_service import MLService
from .profiling_service import profiling_service

logger = get_logger("insightflow.agent")

PIPELINE_STEPS = [
    ("profile", "Profile data"),
    ("quality", "Assess quality"),
    ("clean", "Clean data"),
    ("analytics", "Generate analytics"),
    ("train", "Train models"),
    ("explain", "Explain model"),
    ("summarise", "Generate summary"),
]


class AgentService:
    def __init__(self, db: Session):
        self.db = db
        self.ml = MLService(db)
        self.explainer = ExplainabilityService(db)

    def run(
        self,
        dataset: models.Dataset,
        user_id: int,
        apply_cleaning: bool = True,
        train: bool = True,
    ) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        state: dict[str, Any] = {}
        started = time.perf_counter()

        # --- 1. profile --------------------------------------------------
        with self._step(steps, "profile", "Profile data") as step:
            loaded = load_dataset(dataset, prefer="original", max_rows=settings.PROFILE_SAMPLE_ROWS)
            state["original_rows"] = loaded.total_rows
            step["result"] = {
                "rows": loaded.total_rows,
                "columns": int(loaded.df.shape[1]),
                "data_source": loaded.source,
                "sampled": loaded.sampled,
            }
            step["summary"] = f"Read {loaded.total_rows:,} rows across {loaded.df.shape[1]} columns."
            state["df"] = loaded.df

        # --- 2. quality --------------------------------------------------
        if "df" in state:
            with self._step(steps, "quality", "Assess quality") as step:
                report = profiling_service.full_profile(
                    state["df"], dataset.size_bytes or 0, source="original"
                )
                state["quality"] = report
                score = report["quality"]["overall_score"]
                step["result"] = {
                    "overall_score": score,
                    "grade": report["quality"]["grade"],
                    "warnings": report["warnings"],
                    "recommendations": report["recommendations"],
                }
                step["summary"] = (
                    f"Quality score {score}/100 ({report['quality']['grade']}), "
                    f"{len(report['warnings'])} issue(s) found."
                )
        else:
            self._skip(steps, "quality", "Assess quality", "The dataset could not be read.")

        # --- 3. clean ----------------------------------------------------
        if "df" not in state:
            self._skip(steps, "clean", "Clean data", "The dataset could not be read.")
        elif not apply_cleaning:
            self._skip(steps, "clean", "Clean data", "Cleaning was not requested for this run.")
        else:
            with self._step(steps, "clean", "Clean data") as step:
                plan = cleaning_service.recommend_config(state["df"])
                config = CleaningConfig(**plan["recommended_config"])
                full = load_dataset(dataset, prefer="original")
                cleaned_df, report = cleaning_service.apply_config(full.df, config)

                os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
                target = cleaned_path_for(dataset)
                write_dataframe(cleaned_df, target)
                dataset.cleaned_path = target
                self.db.commit()

                state["cleaned_rows"] = int(cleaned_df.shape[0])
                state["cleaning"] = report
                step["result"] = report
                step["summary"] = (
                    f"{report['before']['rows']:,} rows in, {report['after']['rows']:,} out; "
                    f"{report['missing_values_filled']} missing value(s) filled."
                )

        # --- 4. analytics ------------------------------------------------
        with self._step(steps, "analytics", "Generate analytics") as step:
            loaded = load_dataset(dataset, max_rows=settings.PROFILE_SAMPLE_ROWS)
            dashboard = analytics_service.auto_dashboard(loaded.df)
            state["dashboard"] = dashboard
            step["result"] = dashboard
            step["summary"] = (
                f"{len(dashboard['kpis'])} KPI(s) computed"
                + (f", target column {dashboard['target_column']}." if dashboard["target_column"] else ".")
            )

        # --- 5. train ----------------------------------------------------
        if not train:
            self._skip(steps, "train", "Train models", "Model training was not requested for this run.")
        else:
            with self._step(steps, "train", "Train models") as step:
                result = self.ml.train(dataset, user_id, TrainRequest())
                state["model"] = result
                step["result"] = result
                best = next((r for r in result["results"] if r["model"] == result["best_model"]), None)
                step["summary"] = (
                    f"{result['best_model']} won out of {len(result['results'])} models "
                    f"predicting {result['target_column']}"
                    + (f" (score {best['score']:.3f})." if best and best.get("score") is not None else ".")
                )

        # --- 6. explain --------------------------------------------------
        if "model" not in state:
            self._skip(
                steps, "explain", "Explain model",
                "No model was trained, so there is nothing to explain.",
            )
        else:
            with self._step(steps, "explain", "Explain model") as step:
                explanation = self.explainer.explain(dataset, user_id)
                state["explanation"] = explanation
                step["result"] = explanation
                top = explanation["feature_importance"][0] if explanation["feature_importance"] else None
                step["summary"] = (
                    f"Top driver {top['feature']} ({top['importance_pct']}%) via "
                    f"{explanation['method']}." if top else "No features carried measurable importance."
                )

        # --- 7. summarise ------------------------------------------------
        with self._step(steps, "summarise", "Generate summary") as step:
            summary = self._summary(dataset, state)
            step["result"] = summary
            step["summary"] = "Pipeline summary assembled."

        elapsed = round(time.perf_counter() - started, 2)
        completed = sum(1 for s in steps if s["status"] == "completed")
        failed = [s for s in steps if s["status"] == "failed"]

        return to_jsonable({
            "steps": steps,
            "summary": self._summary(dataset, state),
            "duration_sec": elapsed,
            "steps_completed": completed,
            "steps_total": len(steps),
            "steps_failed": len(failed),
            "status": "completed" if not failed else "completed_with_errors",
        })

    # -------------------------------------------------------------- helpers
    class _StepContext:
        """Records status and measured duration for one pipeline step."""

        def __init__(self, steps: list[dict[str, Any]], key: str, label: str):
            self.step = {
                "key": key, "step": label, "status": "running",
                "duration_sec": None, "result": None, "summary": None, "error": None,
            }
            steps.append(self.step)
            self._started = 0.0

        def __enter__(self) -> dict[str, Any]:
            self._started = time.perf_counter()
            return self.step

        def __exit__(self, exc_type, exc, tb) -> bool:
            self.step["duration_sec"] = round(time.perf_counter() - self._started, 3)
            if exc is None:
                self.step["status"] = "completed"
                return False

            # A step that cannot run is reported and the pipeline continues; only
            # genuinely unexpected errors are logged as such.
            if isinstance(exc, AppException):
                self.step["status"] = "skipped"
                self.step["error"] = exc.detail
                self.step["summary"] = f"Skipped: {exc.detail}"
            else:
                self.step["status"] = "failed"
                self.step["error"] = f"{type(exc).__name__}: {exc}"
                self.step["summary"] = "This step failed unexpectedly."
                logger.error("Agent step %s failed: %s", self.step["key"], exc, exc_info=True)
            return True  # suppress, so later steps still run

    def _step(self, steps: list[dict[str, Any]], key: str, label: str) -> _StepContext:
        return self._StepContext(steps, key, label)

    @staticmethod
    def _skip(steps: list[dict[str, Any]], key: str, label: str, reason: str) -> None:
        steps.append({
            "key": key, "step": label, "status": "skipped", "duration_sec": 0.0,
            "result": None, "summary": f"Skipped: {reason}", "error": reason,
        })

    @staticmethod
    def _summary(dataset: models.Dataset, state: dict[str, Any]) -> dict[str, Any]:
        model = state.get("model")
        explanation = state.get("explanation")
        quality = state.get("quality")
        cleaning = state.get("cleaning")
        dashboard = state.get("dashboard")

        warnings: list[str] = []
        if quality:
            warnings += [
                w["message"] for w in quality.get("warnings", [])
                if w["severity"] in ("danger", "warning")
            ]
        if model:
            warnings += list(model.get("warnings") or [])

        next_actions: list[str] = []
        if quality:
            next_actions += [r["action"] for r in quality.get("recommendations", [])[:3]]
        if model:
            next_actions.append("Download the trained model or review the leaderboard.")
        else:
            next_actions.append("Train a model to add predictions and explainability.")
        next_actions.append("Download the PDF report for a shareable summary.")

        return {
            "dataset": dataset.filename,
            "rows_before_cleaning": state.get("original_rows"),
            "rows_after_cleaning": state.get("cleaned_rows"),
            "quality_score": quality["quality"]["overall_score"] if quality else None,
            "quality_grade": quality["quality"]["grade"] if quality else None,
            "cleaning_changes": {
                "rows_removed": cleaning.get("rows_removed") if cleaning else None,
                "missing_values_filled": cleaning.get("missing_values_filled") if cleaning else None,
                "steps_applied": len(cleaning.get("steps", [])) if cleaning else 0,
            },
            "kpis": (dashboard or {}).get("kpis", []),
            "target_column": model["target_column"] if model else (dashboard or {}).get("target_column"),
            "best_model": model["best_model"] if model else None,
            "model_version": model.get("model_version") if model else None,
            "task_type": model["task_type"] if model else None,
            "top_feature": (
                explanation["feature_importance"][0]["feature"]
                if explanation and explanation.get("feature_importance") else None
            ),
            "explanation_method": explanation["method"] if explanation else None,
            "warnings": warnings[:8],
            "next_actions": next_actions,
        }
