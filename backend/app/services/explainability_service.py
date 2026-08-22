"""
Model explainability.

Two things were wrong with the original implementation:

1. It trained a brand-new RandomForest on every request and explained *that*,
   not the model the user had actually trained and was looking at. The numbers
   on the Explainability tab therefore described a model that existed nowhere
   else in the product.
2. It fell back from SHAP to `feature_importances_` inside a bare `except`,
   while the UI told the user the results were "powered by SHAP". The response
   carried no indication of which method produced the numbers.

Both are fixed here: explanations come from the persisted best model of the
latest ModelRun, and the response always states `method` and `fallback_used`,
with `fallback_reason` when SHAP could not run.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from .. import models
from ..core.config import settings
from ..core.exceptions import NotFoundError
from ..core.serialization import safe_float, to_jsonable
from .dataframe_io import load_dataset
from .ml_service import MLService, prep_features

# SHAP on a large frame is slow and memory-hungry; a few hundred rows gives a
# stable global importance ranking.
SHAP_SAMPLE_ROWS = 200

METHOD_LABELS = {
    "shap": "SHAP (Shapley additive explanations)",
    "model_feature_importance": "Model feature importance",
    "coefficients": "Linear model coefficients (standardised by feature spread)",
    "permutation_importance": "Permutation importance (model-agnostic)",
}

# Permutation importance re-scores the model once per feature per repeat, so the
# sample and repeat count are kept small enough to stay inside a request.
PERMUTATION_SAMPLE_ROWS = 300
PERMUTATION_REPEATS = 5


class ExplainabilityService:
    def __init__(self, db: Session):
        self.db = db
        self.ml = MLService(db)

    def explain(self, dataset: models.Dataset, user_id: int) -> dict[str, Any]:
        run = self.ml.latest_run(dataset.id, user_id)
        if run is None:
            raise NotFoundError(
                "No trained model for this dataset yet. Train a model first, then "
                "explanations will describe that model.",
                error_code="no_trained_model",
            )

        pipeline = self.ml.load_persisted_model(run)
        target = run.target_column
        classification = run.task_type == "classification"

        loaded = load_dataset(
            dataset,
            prefer="cleaned" if run.data_source == "cleaned" else "original",
            max_rows=settings.MAX_TRAIN_ROWS,
        )
        df = loaded.df
        if target not in df.columns:
            raise NotFoundError(
                f"The target column '{target}' from that training run is no longer in this "
                "dataset. Re-train to refresh the explanation.",
                error_code="target_column_missing",
            )

        # Rebuild features exactly as training did, then align to the stored
        # feature list so the matrix matches what the model expects.
        X, y, _, _cat, _num = prep_features(df, target, excluded=(run.config or {}).get("excluded_columns") or [])
        expected = list(run.features or X.columns)
        missing = [c for c in expected if c not in X.columns]
        if missing:
            raise NotFoundError(
                f"{len(missing)} feature column(s) from that run are missing now "
                f"({', '.join(missing[:4])}). Re-train to refresh the explanation.",
                error_code="feature_columns_missing",
            )
        X = X[expected]

        importance, method, fallback_reason, signed = self._compute_importance(
            pipeline, X, y, classification
        )
        if importance is None:
            raise NotFoundError(
                "This model could not be explained by any available method "
                f"({fallback_reason}).",
                error_code="explanation_unavailable",
            )

        total = float(np.sum(np.abs(importance))) or 1.0
        ranked = sorted(
            [
                {
                    "feature": str(col),
                    "importance_pct": safe_float(abs(float(val)) / total * 100, 2),
                    "direction": (
                        None if signed is None
                        else ("increases" if signed.get(str(col), 0) >= 0 else "decreases")
                    ),
                }
                for col, val in zip(expected, importance)
            ],
            key=lambda item: item["importance_pct"] or 0,
            reverse=True,
        )

        return to_jsonable({
            "method": method,
            "method_label": METHOD_LABELS.get(method, method),
            "fallback_used": method != "shap",
            "fallback_reason": fallback_reason,
            "target_column": target,
            "task_type": run.task_type,
            "model_name": run.best_model_name,
            "model_version": run.version,
            "model_run_id": run.id,
            "trained_at": run.created_at.isoformat() if run.created_at else None,
            "data_source": loaded.source,
            "rows_explained": min(SHAP_SAMPLE_ROWS, int(len(X))) if method == "shap" else int(len(X)),
            "feature_importance": ranked,
            "top_drivers": ranked[:5],
            "interpretation": self._interpretation(ranked, target, run.best_model_name, method),
            "caveats": [
                "Feature importance shows statistical association, not causation. A high-ranking "
                "feature is not proven to cause the outcome.",
                "Importances are relative to this model and this dataset; a different model or a "
                "different sample can reorder them.",
                (
                    "Correlated features share credit, so a genuinely important driver can appear "
                    "low if a near-duplicate column absorbs its contribution."
                ),
            ],
        })

    def _compute_importance(
        self, pipeline, X: pd.DataFrame, y, classification: bool
    ) -> tuple[np.ndarray | None, str, str | None, dict[str, float] | None]:
        """Returns (importance, method, fallback_reason, signed_direction).

        Tries, in order: SHAP -> the estimator's own importances -> linear
        coefficients -> permutation importance. Permutation importance is the
        universal backstop: it works for any estimator (KNN, SVM, anything),
        so no model type leaves the user with an empty Explainability tab.
        The reason SHAP was skipped is always reported.
        """
        estimator = pipeline
        preprocessor = None
        if hasattr(pipeline, "named_steps"):
            steps = getattr(pipeline, "named_steps", {})
            if "model" in steps:
                estimator = steps["model"]
            if "preprocessor" in steps:
                preprocessor = steps["preprocessor"]

        has_ct = preprocessor is not None and hasattr(preprocessor, "transformers_")
        original_cols = list(X.columns)

        shap_values, reason = self._try_shap(pipeline, estimator, X, preprocessor)
        if shap_values is not None:
            if has_ct:
                shap_values = self._aggregate_to_original(shap_values, preprocessor, original_cols)
            signed = None
            try:
                if shap_values.ndim == 2 and shap_values.shape[1] == len(original_cols):
                    signed = {
                        str(col): float(v)
                        for col, v in zip(original_cols, np.mean(shap_values, axis=0))
                    }
            except Exception:  # noqa: BLE001
                signed = None
            return np.mean(np.abs(shap_values), axis=0), "shap", None, signed

        if hasattr(estimator, "feature_importances_"):
            imp = np.asarray(estimator.feature_importances_)
            if has_ct:
                imp = self._aggregate_to_original(imp, preprocessor, original_cols)
            return imp, "model_feature_importance", reason, None

        if hasattr(estimator, "coef_"):
            coef = np.asarray(estimator.coef_)
            if coef.ndim > 1:
                coef = np.mean(np.abs(coef), axis=0)
            coef = np.ravel(coef)
            if has_ct:
                coef = self._aggregate_to_original(coef, preprocessor, original_cols)
                signed = {str(c): float(v) for c, v in zip(original_cols, coef)}
            else:
                signed = {str(c): float(v) for c, v in zip(X.columns, coef)}
                already_scaled = "scaler" in getattr(pipeline, "named_steps", {})
                if not already_scaled:
                    spread = X.std(numeric_only=True).reindex(X.columns).fillna(0).to_numpy()
                    if np.any(spread > 0):
                        coef = coef * spread
            return coef, "coefficients", reason, signed

        permuted, perm_reason = self._try_permutation(pipeline, X, y, classification)
        if permuted is not None:
            return permuted, "permutation_importance", reason, None

        return None, "unavailable", f"{reason}; {perm_reason}", None

    @staticmethod
    def _aggregate_to_original(
        values: np.ndarray, preprocessor, original_cols: list[str]
    ) -> np.ndarray:
        """Map importances from the transformed feature space back to the
        original columns by summing one-hot contributions per feature."""
        col_to_idx = {col: i for i, col in enumerate(original_cols)}
        is_2d = values.ndim == 2
        result = np.zeros((values.shape[0], len(original_cols))) if is_2d else np.zeros(len(original_cols))
        pos = 0
        for tname, transformer, cols in preprocessor.transformers_:
            for i, col in enumerate(cols):
                j = col_to_idx.get(str(col))
                if tname == "cat" and hasattr(transformer, "categories_"):
                    n = len(transformer.categories_[i])
                    if j is not None and pos + n <= (values.shape[1] if is_2d else len(values)):
                        if is_2d:
                            result[:, j] = np.sum(np.abs(values[:, pos:pos + n]), axis=1)
                        else:
                            result[j] = float(np.sum(np.abs(values[pos:pos + n])))
                    pos += n
                else:
                    if j is not None and pos < (values.shape[1] if is_2d else len(values)):
                        if is_2d:
                            result[:, j] = values[:, pos]
                        else:
                            result[j] = float(np.abs(values[pos]))
                    pos += 1
        return result

    @staticmethod
    def _try_permutation(
        pipeline, X: pd.DataFrame, y, classification: bool
    ) -> tuple[np.ndarray | None, str | None]:
        """Model-agnostic importance: shuffle each column and measure how much
        the score degrades. Works on estimators that expose neither importances
        nor coefficients."""
        try:
            from sklearn.inspection import permutation_importance

            if len(X) > PERMUTATION_SAMPLE_ROWS:
                sample_idx = np.random.default_rng(42).choice(
                    len(X), PERMUTATION_SAMPLE_ROWS, replace=False
                )
                X_s = X.iloc[sample_idx]
                y_s = np.asarray(y)[sample_idx]
            else:
                X_s, y_s = X, np.asarray(y)

            result = permutation_importance(
                pipeline, X_s, y_s,
                n_repeats=PERMUTATION_REPEATS,
                random_state=42,
                scoring="f1_weighted" if classification else "r2",
                n_jobs=1,
            )
            # Negative means shuffling *helped* - clamp to zero, since a feature
            # cannot contribute less than nothing.
            return np.clip(result.importances_mean, 0, None), None
        except Exception as exc:  # noqa: BLE001
            return None, f"permutation importance failed ({type(exc).__name__})"

    @staticmethod
    def _try_shap(pipeline, estimator, X: pd.DataFrame, preprocessor=None) -> tuple[np.ndarray | None, str | None]:
        """Attempt SHAP, returning (values, reason_it_failed)."""
        try:
            import shap
        except ImportError:
            return None, "the shap package is not installed on the server"

        sample = X.sample(min(SHAP_SAMPLE_ROWS, len(X)), random_state=42)
        try:
            transformed = sample
            steps = getattr(pipeline, "named_steps", {})
            if preprocessor is not None and hasattr(preprocessor, "transform"):
                transformed = preprocessor.transform(sample)
                if "scaler" in steps:
                    transformed = steps["scaler"].transform(transformed)
            elif "scaler" in steps:
                transformed = pd.DataFrame(
                    steps["scaler"].transform(sample),
                    columns=sample.columns,
                    index=sample.index,
                )
            explainer = shap.TreeExplainer(estimator)
            values = explainer.shap_values(transformed, check_additivity=False)
        except Exception as exc:  # noqa: BLE001 - non-tree models land here by design
            return None, f"SHAP does not support this model type ({type(exc).__name__})"

        try:
            values = np.asarray(values) if not isinstance(values, list) else np.mean(
                [np.abs(v) for v in values], axis=0
            )
            if values.ndim == 3:
                values = values.mean(axis=2)
            if values.ndim != 2:
                return None, "SHAP returned an unexpected value shape"
            return values, None
        except Exception as exc:  # noqa: BLE001
            return None, f"SHAP output could not be reduced ({type(exc).__name__})"

    @staticmethod
    def _interpretation(
        ranked: list[dict[str, Any]], target: str, model_name: str | None, method: str
    ) -> str:
        if not ranked:
            return "No features carried measurable importance for this model."
        top = ranked[0]
        source = (
            "Shapley values computed against the trained model"
            if method == "shap"
            else f"the {METHOD_LABELS.get(method, method).lower()} reported by the model"
        )
        lines = [
            f"For the {model_name or 'trained'} model predicting {target}, "
            f"{top['feature']} is the strongest single driver, accounting for "
            f"{top['importance_pct']}% of total measured importance, based on {source}."
        ]
        if len(ranked) >= 3:
            rest = ", ".join(f"{r['feature']} ({r['importance_pct']}%)" for r in ranked[1:3])
            lines.append(f"It is followed by {rest}.")
        weak = [r for r in ranked if (r["importance_pct"] or 0) < 1]
        if weak:
            lines.append(
                f"{len(weak)} feature(s) contributed under 1% each and could likely be dropped "
                "without hurting the model."
            )
        return " ".join(lines)
