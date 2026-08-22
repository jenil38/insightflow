"""
Machine-learning training engine.

This is the logic that used to live inside the `POST /train` route function.
It moved here because `agent.py` and `report.py` were calling that route
function directly - so generating a PDF retrained all twelve models and wrote a
new ModelRun version every single time. Now the router, the agent, and the
report generator all call `MLService.train()` or, better,
`MLService.latest_run()` to reuse what has already been trained.

Capabilities beyond the original module:
- user-selected target, task type, excluded columns, split, folds, tuning
- per-model failure isolation (one broken estimator no longer kills the run)
- classification: ROC-AUC where valid, confusion matrix, class distribution
- regression: RMSE, MAPE only when mathematically valid, residual + predicted
  scatter data for charting
- reproducibility metadata persisted with every run
"""

from __future__ import annotations

import os
import time
import warnings as _warnings
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    AdaBoostClassifier,
    AdaBoostRegressor,
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import (
    RandomizedSearchCV,
    cross_val_score,
    train_test_split,
)
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
from sklearn.base import clone as clone_estimator
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, OneHotEncoder, StandardScaler
from sklearn.svm import SVC, SVR
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
from sqlalchemy.orm import Session

from .. import models
from ..core.config import settings
from ..core.exceptions import NotFoundError, ValidationAppError
from ..core.serialization import safe_float, to_jsonable
from ..schemas import TrainRequest
from .dataframe_io import load_dataset
from .profiling_service import (
    build_warnings,
    compute_quality_scores,
    infer_semantic_type,
    infer_task_type,
    is_continuous,
    profile_column,
    recommend_targets,
)

SCALE_SENSITIVE = {"KNN", "SVM", "Logistic Regression", "Linear Regression"}

# Small deliberate search budgets: this runs inside a request, so the goal is
# "better than defaults", not an exhaustive sweep.
TUNING_GRIDS: dict[str, dict[str, list]] = {
    "Random Forest": {"n_estimators": [100, 200, 300], "max_depth": [None, 8, 16]},
    "Extra Trees": {"n_estimators": [100, 200, 300], "max_depth": [None, 8, 16]},
    "Gradient Boosting": {
        "n_estimators": [100, 200],
        "learning_rate": [0.05, 0.1, 0.2],
        "max_depth": [2, 3, 4],
    },
    "AdaBoost": {"n_estimators": [50, 100, 200], "learning_rate": [0.5, 1.0, 1.5]},
    "XGBoost": {
        "n_estimators": [100, 200, 300],
        "max_depth": [3, 5, 7],
        "learning_rate": [0.05, 0.1, 0.2],
    },
    "LightGBM": {
        "n_estimators": [100, 200, 300],
        "num_leaves": [15, 31, 63],
        "learning_rate": [0.05, 0.1, 0.2],
    },
    "CatBoost": {
        "iterations": [100, 200, 300],
        "depth": [4, 6, 8],
        "learning_rate": [0.05, 0.1, 0.2],
    },
    "Decision Tree": {"max_depth": [None, 5, 10, 20]},
    "KNN": {"n_neighbors": [3, 5, 8, 12]},
}

MIN_TRAINING_ROWS = 20
# A text column is dropped rather than label-encoded when it has too many
# distinct values in absolute terms, OR when it is near-unique per row.
# The ratio test is what actually catches identifiers: a 50-distinct-value
# column is fine in 5,000 rows and is a row ID in 50 rows, and label-encoding
# an ID into 0..n just injects noise the trees will happily overfit.
MAX_CATEGORICAL_CARDINALITY = 50
MAX_CATEGORICAL_UNIQUE_RATIO = 0.9


def _optional_estimators(classification: bool) -> dict[str, Any]:
    """XGBoost / LightGBM / CatBoost are heavy optional deps. Import them
    individually so a missing or broken wheel degrades the leaderboard instead
    of taking down the whole endpoint."""
    out: dict[str, Any] = {}
    try:
        from xgboost import XGBClassifier, XGBRegressor

        out["XGBoost"] = (
            XGBClassifier(eval_metric="logloss", random_state=42, verbosity=0)
            if classification
            else XGBRegressor(random_state=42, verbosity=0)
        )
    except Exception:  # noqa: BLE001 - optional dependency
        pass
    try:
        from lightgbm import LGBMClassifier, LGBMRegressor

        out["LightGBM"] = (
            LGBMClassifier(random_state=42, verbosity=-1)
            if classification
            else LGBMRegressor(random_state=42, verbosity=-1)
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from catboost import CatBoostClassifier, CatBoostRegressor

        out["CatBoost"] = (
            CatBoostClassifier(
                random_state=42, verbose=False, allow_writing_files=False
            )
            if classification
            else CatBoostRegressor(
                random_state=42, verbose=False, allow_writing_files=False
            )
        )
    except Exception:  # noqa: BLE001
        pass
    return out


def build_candidates(classification: bool) -> dict[str, Any]:
    if classification:
        base = {
            "Baseline (majority)": DummyClassifier(strategy="most_frequent"),
            "Logistic Regression": LogisticRegression(max_iter=1000),
            "Decision Tree": DecisionTreeClassifier(random_state=42),
            "Random Forest": RandomForestClassifier(n_estimators=100, random_state=42),
            "Extra Trees": ExtraTreesClassifier(n_estimators=100, random_state=42),
            "Gradient Boosting": GradientBoostingClassifier(random_state=42),
            "AdaBoost": AdaBoostClassifier(random_state=42),
            "KNN": KNeighborsClassifier(),
            "SVM": SVC(probability=True, random_state=42),
            "Naive Bayes": GaussianNB(),
        }
    else:
        base = {
            "Baseline (mean)": DummyRegressor(strategy="mean"),
            "Linear Regression": LinearRegression(),
            "Decision Tree": DecisionTreeRegressor(random_state=42),
            "Random Forest": RandomForestRegressor(n_estimators=100, random_state=42),
            "Extra Trees": ExtraTreesRegressor(n_estimators=100, random_state=42),
            "Gradient Boosting": GradientBoostingRegressor(random_state=42),
            "AdaBoost": AdaBoostRegressor(random_state=42),
            "KNN": KNeighborsRegressor(),
            "SVM": SVR(),
        }
    base.update(_optional_estimators(classification))
    return base


def make_pipeline(name: str, model, preprocessor: ColumnTransformer | None = None):
    """Wrap the model in a Pipeline with optional preprocessing and scaling."""
    steps = []
    if preprocessor is not None:
        steps.append(("preprocessor", preprocessor))
    if name in SCALE_SENSITIVE:
        steps.append(("scaler", StandardScaler()))
    steps.append(("model", model))
    return Pipeline(steps)


def prep_features(
    df: pd.DataFrame, target: str, excluded: list[str] | None = None
) -> tuple[pd.DataFrame, pd.Series, list[str], list[str], list[str]]:
    """Returns (X, y, dropped_columns, cat_cols, num_cols).

    Categorical columns are left as strings — encoding happens inside the
    sklearn Pipeline (via ColumnTransformer) so it fits only on training data,
    preventing target leakage from the encoder seeing test-set categories."""
    excluded = [c for c in (excluded or []) if c != target]
    work = df.dropna(subset=[target]).copy()
    y = work[target]
    X = work.drop(columns=[target])

    dropped: list[str] = []
    for col in list(X.columns):
        if col in excluded:
            X = X.drop(columns=[col])
            dropped.append(str(col))

    cat_cols: list[str] = []
    num_cols: list[str] = []

    for col in list(X.columns):
        series = X[col]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            distinct = int(series.nunique())
            unique_ratio = distinct / max(len(series), 1)
            too_many = distinct > MAX_CATEGORICAL_CARDINALITY
            near_unique = distinct > 1 and unique_ratio >= MAX_CATEGORICAL_UNIQUE_RATIO
            if too_many or near_unique:
                X = X.drop(columns=[col])
                dropped.append(str(col))
            else:
                X[col] = series.fillna("_missing_").astype(str)
                cat_cols.append(str(col))
        elif pd.api.types.is_datetime64_any_dtype(series):
            X[col] = pd.to_datetime(series, errors="coerce").astype("int64") // 10**9
            num_cols.append(str(col))
        elif pd.api.types.is_bool_dtype(series):
            X[col] = series.astype(int)
            num_cols.append(str(col))
        else:
            X[col] = pd.to_numeric(series, errors="coerce")
            num_cols.append(str(col))

    for col in list(X.columns):
        if col not in cat_cols and not pd.api.types.is_numeric_dtype(X[col]):
            X = X.drop(columns=[col])
            dropped.append(str(col))
            if col in num_cols:
                num_cols.remove(col)

    return X, y, dropped, cat_cols, num_cols


def build_preprocessor(cat_cols: list[str], num_cols: list[str]) -> ColumnTransformer:
    """ColumnTransformer that one-hot-encodes categoricals and median-imputes
    numerics. Fitted only on training data inside the sklearn Pipeline."""
    transformers = []
    if cat_cols:
        transformers.append(
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                cat_cols,
            )
        )
    if num_cols:
        transformers.append(
            (
                "num",
                SimpleImputer(strategy="median"),
                num_cols,
            )
        )
    return ColumnTransformer(transformers, remainder="drop")


def is_classification(y: pd.Series) -> bool:
    """Backward-compatible helper kept for existing importers."""
    semantic = infer_semantic_type(y)
    return infer_task_type(y, semantic, int(y.dropna().nunique())) == "classification"


def detect_data_leakage(
    X: pd.DataFrame, y: pd.Series, classification: bool
) -> list[str]:
    """Flag features that are near-perfect stand-ins for the target - usually a
    duplicated or derived column rather than a real predictor."""
    found: list[str] = []
    try:
        if classification:
            y_series = pd.Series(y).reset_index(drop=True)
            for col in X.columns:
                column = X[col].reset_index(drop=True)
                distinct = column.nunique()
                if distinct <= 1 or distinct > y_series.nunique() + 2:
                    continue
                grouped = y_series.groupby(column).nunique()
                if (grouped <= 1).all() and distinct >= y_series.nunique():
                    found.append(
                        f"Column '{col}' may leak the target (near 1:1 mapping to the label)."
                    )
        else:
            y_numeric = pd.to_numeric(pd.Series(y), errors="coerce")
            for col in X.select_dtypes(include=[np.number]).columns:
                if X[col].std() == 0:
                    continue
                corr = np.corrcoef(X[col].fillna(0), y_numeric.fillna(0))[0, 1]
                if np.isfinite(corr) and abs(corr) > 0.98:
                    found.append(
                        f"Column '{col}' is {corr:.3f} correlated with the target - possible leakage."
                    )
    except Exception:  # noqa: BLE001 - leakage detection must never fail a run
        pass
    return found


def detect_class_imbalance(y) -> str | None:
    counts = pd.Series(y).value_counts()
    if len(counts) < 2:
        return None
    ratio = counts.min() / counts.max()
    if ratio < 0.15:
        return (
            f"Class imbalance detected - the minority class is only {ratio:.1%} the size of the "
            "majority class. Prefer F1 or recall over accuracy when judging these models."
        )
    return None


def evaluate(model, X_test, y_test, classification: bool) -> dict[str, Any]:
    """Task-appropriate metrics only - no R^2 on a classifier, no F1 on a regressor."""
    preds = model.predict(X_test)

    if classification:
        metrics: dict[str, Any] = {
            "accuracy": safe_float(accuracy_score(y_test, preds)),
            "precision": safe_float(
                precision_score(y_test, preds, average="weighted", zero_division=0)
            ),
            "recall": safe_float(
                recall_score(y_test, preds, average="weighted", zero_division=0)
            ),
            "f1": safe_float(
                f1_score(y_test, preds, average="weighted", zero_division=0)
            ),
        }
        # ROC-AUC is only well-defined for binary problems with probabilities
        # and both classes present in the test split.
        try:
            classes = np.unique(y_test)
            if len(classes) == 2 and hasattr(model, "predict_proba"):
                proba = model.predict_proba(X_test)[:, 1]
                metrics["roc_auc"] = safe_float(roc_auc_score(y_test, proba))
        except Exception:  # noqa: BLE001
            pass
        return metrics

    rmse = float(np.sqrt(mean_squared_error(y_test, preds)))
    metrics = {
        "r2": safe_float(r2_score(y_test, preds)),
        "mae": safe_float(mean_absolute_error(y_test, preds)),
        "rmse": safe_float(rmse),
    }
    # MAPE is undefined when any actual value is zero, so only report it when
    # every actual is non-zero.
    actuals = np.asarray(y_test, dtype=float)
    if actuals.size and not np.any(actuals == 0):
        mape = float(
            np.mean(np.abs((actuals - np.asarray(preds, dtype=float)) / actuals)) * 100
        )
        metrics["mape"] = safe_float(mape, 2)
    return metrics


def score_of(metrics: dict[str, Any], classification: bool) -> float:
    """The single number the leaderboard sorts on."""
    key = "f1" if classification else "r2"
    value = metrics.get(key)
    return float(value) if value is not None else float("-inf")


class MLService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------- options
    def config_options(
        self, dataset: models.Dataset, use_cleaned: bool = True
    ) -> dict[str, Any]:
        """Everything the pre-training configuration screen needs, so the user
        picks from real columns instead of typing names."""
        loaded = load_dataset(
            dataset,
            prefer="auto" if use_cleaned else "original",
            max_rows=settings.PROFILE_SAMPLE_ROWS,
        )
        df = loaded.df
        column_profiles = [profile_column(df, c) for c in df.columns]
        scores = compute_quality_scores(df)

        suggested_exclusions = []
        for prof in column_profiles:
            if (
                (prof["unique_pct"] or 0) >= 99.9
                and prof["non_null_count"] > 10
                # A continuous measurement is unique per row by nature; only
                # discrete columns are identifier-like.
                and not is_continuous(df[prof["column"]])
            ):
                suggested_exclusions.append(
                    {
                        "column": prof["column"],
                        "reason": "Looks like a unique identifier.",
                    }
                )
            elif prof["is_constant"]:
                suggested_exclusions.append(
                    {
                        "column": prof["column"],
                        "reason": "Holds a single value, so carries no signal.",
                    }
                )
            elif (prof["missing_pct"] or 0) >= 60:
                suggested_exclusions.append(
                    {
                        "column": prof["column"],
                        "reason": f"{prof['missing_pct']}% of values are missing.",
                    }
                )

        candidates = recommend_targets(df, limit=8)
        return to_jsonable(
            {
                "columns": [
                    {
                        "column": p["column"],
                        "semantic_type": p["semantic_type"],
                        "dtype": p["dtype"],
                        "missing_pct": p["missing_pct"],
                        "unique_count": p["unique_count"],
                        "is_constant": p["is_constant"],
                    }
                    for p in column_profiles
                ],
                "target_candidates": candidates,
                "recommended_target": candidates[0]["column"] if candidates else None,
                "recommended_task_type": candidates[0]["task_type"]
                if candidates
                else None,
                "suggested_exclusions": suggested_exclusions,
                "warnings": build_warnings(df, column_profiles, scores),
                "row_count": loaded.row_count,
                "data_source": loaded.source,
            }
        )

    # -------------------------------------------------------------- train
    def train(
        self, dataset: models.Dataset, user_id: int, request: TrainRequest | None = None
    ) -> dict[str, Any]:
        request = request or TrainRequest()
        loaded = load_dataset(
            dataset,
            prefer="auto" if request.use_cleaned else "original",
            max_rows=settings.MAX_TRAIN_ROWS,
        )
        df = loaded.df

        target = request.target_column
        if target is not None and target not in df.columns:
            raise ValidationAppError(
                f"Column '{target}' is not in this dataset.",
                error_code="unknown_target_column",
                status_code=400,
            )
        if target is None:
            candidates = recommend_targets(df, limit=1)
            if not candidates:
                raise ValidationAppError(
                    "No suitable target column could be identified. Pick one explicitly.",
                    error_code="no_target_column",
                    status_code=400,
                )
            target = candidates[0]["column"]

        X, y, dropped, cat_cols, num_cols = prep_features(
            df, target, request.excluded_columns
        )
        if X.shape[1] == 0:
            raise ValidationAppError(
                "No usable feature columns remain after preparation. Try excluding fewer columns.",
                error_code="no_features",
                status_code=400,
            )
        if len(X) < MIN_TRAINING_ROWS:
            raise ValidationAppError(
                f"Only {len(X)} usable rows - at least {MIN_TRAINING_ROWS} are needed to train.",
                error_code="insufficient_rows",
                status_code=400,
            )

        if request.task_type == "auto":
            semantic = infer_semantic_type(y)
            classification = (
                infer_task_type(y, semantic, int(y.dropna().nunique()))
                == "classification"
            )
        else:
            classification = request.task_type == "classification"

        if classification and y.nunique() < 2:
            raise ValidationAppError(
                "The target needs at least 2 distinct classes to train a classifier.",
                error_code="single_class_target",
                status_code=400,
            )
        if not classification:
            y_numeric = pd.to_numeric(y, errors="coerce")
            if y_numeric.isna().all():
                raise ValidationAppError(
                    f"Column '{target}' is not numeric, so it cannot be used for regression. "
                    "Choose classification instead, or pick a numeric target.",
                    error_code="non_numeric_regression_target",
                    status_code=400,
                )
            if float(y_numeric.std() or 0) == 0:
                raise ValidationAppError(
                    "The target has zero variance - there is nothing to predict.",
                    error_code="zero_variance_target",
                    status_code=400,
                )
            y = y_numeric

        run_warnings = detect_data_leakage(X, y, classification)
        class_distribution: list[dict[str, Any]] = []
        label_names: list[str] | None = None

        if classification:
            imbalance = detect_class_imbalance(y)
            if imbalance:
                run_warnings.append(imbalance)
            counts = pd.Series(y).value_counts()
            class_distribution = [
                {
                    "label": str(k),
                    "count": int(v),
                    "pct": safe_float(v / len(y) * 100, 2),
                }
                for k, v in counts.items()
            ]
            encoder = LabelEncoder()
            y = encoder.fit_transform(y.astype(str))
            label_names = [str(c) for c in encoder.classes_]

        if dropped:
            run_warnings.append(
                f"{len(dropped)} column(s) were not used as features: {', '.join(dropped[:6])}"
                + ("..." if len(dropped) > 6 else "")
            )
        if loaded.sampled:
            run_warnings.append(
                f"Trained on a random sample of {len(X):,} rows out of {loaded.total_rows:,} "
                "to keep training responsive."
            )

        # Stratifying needs at least 2 members per class in the split.
        stratify = None
        if classification:
            counts = pd.Series(y).value_counts()
            if counts.min() >= 2:
                stratify = y
            else:
                run_warnings.append(
                    "Some classes have only one row, so the train/test split could not be stratified."
                )

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=request.test_size, random_state=42, stratify=stratify
        )

        results, failures = self._run_leaderboard(
            X,
            y,
            X_train,
            X_test,
            y_train,
            y_test,
            classification,
            request,
            cat_cols,
            num_cols,
        )
        if not results:
            detail = (
                "; ".join(f"{name}: {err}" for name, err in failures[:3])
                or "unknown error"
            )
            raise ValidationAppError(
                f"Every candidate model failed to train on this data ({detail}).",
                error_code="all_models_failed",
                status_code=400,
            )
        if failures:
            run_warnings.append(
                f"{len(failures)} model(s) failed and were skipped: "
                + ", ".join(name for name, _ in failures)
            )

        results.sort(key=lambda r: r["score"], reverse=True)
        best = results[0]
        diagnostics = self._diagnostics(
            best["_pipeline"], X_test, y_test, classification, label_names
        )

        run = self._persist_run(
            dataset=dataset,
            user_id=user_id,
            request=request,
            target=target,
            classification=classification,
            best=best,
            results=results,
            features=[str(c) for c in X.columns],
            rows_used=int(len(X)),
            data_source=loaded.source,
        )

        leaderboard = [
            {k: v for k, v in r.items() if k != "_pipeline"} for r in results
        ]

        import sklearn

        reproducibility = {
            "random_seed": 42,
            "split_strategy": "stratified"
            if (classification and stratify is not None)
            else "random",
            "test_size": request.test_size,
            "cross_validation_folds": request.cross_validation_folds,
            "sklearn_version": sklearn.__version__,
            "data_source": loaded.source,
            "dataset_rows": loaded.total_rows,
            "rows_used": int(len(X)),
        }

        return to_jsonable(
            {
                "task_type": "classification" if classification else "regression",
                "target_column": target,
                "rows_used": int(len(X)),
                "features_used": [str(c) for c in X.columns],
                "excluded_columns": dropped,
                "results": leaderboard,
                "best_model": best["model"],
                "warnings": run_warnings,
                "model_run_id": run.id if run else None,
                "model_version": run.version if run else None,
                "trained_at": run.created_at.isoformat()
                if run and run.created_at
                else None,
                "data_source": loaded.source,
                "sampled": loaded.sampled,
                "test_size": request.test_size,
                "cross_validation_folds": request.cross_validation_folds,
                "class_distribution": class_distribution,
                "diagnostics": diagnostics,
                "reproducibility": reproducibility,
            }
        )

    def _run_leaderboard(
        self,
        X,
        y,
        X_train,
        X_test,
        y_train,
        y_test,
        classification: bool,
        request: TrainRequest,
        cat_cols: list[str],
        num_cols: list[str],
    ) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        """Fit every candidate, then lightly tune the top two.

        Each model is isolated: one failing estimator is recorded and skipped
        rather than aborting the whole run.
        """
        candidates = build_candidates(classification)
        scoring = "f1_weighted" if classification else "r2"
        folds = self._usable_folds(y, request.cross_validation_folds, classification)
        preprocessor = build_preprocessor(cat_cols, num_cols)

        results: list[dict[str, Any]] = []
        failures: list[tuple[str, str]] = []

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")

            for name, model in candidates.items():
                pipeline = make_pipeline(name, model, clone_estimator(preprocessor))
                start = time.time()
                try:
                    pipeline.fit(X_train, y_train)
                    metrics = evaluate(pipeline, X_test, y_test, classification)
                except Exception as exc:  # noqa: BLE001 - isolate per-model failure
                    failures.append((name, type(exc).__name__))
                    continue
                elapsed = round(time.time() - start, 3)

                cv_score = None
                try:
                    cv_scores = cross_val_score(
                        make_pipeline(name, model, clone_estimator(preprocessor)),
                        X,
                        y,
                        cv=folds,
                        scoring=scoring,
                    )
                    cv_score = safe_float(np.mean(cv_scores))
                except Exception:  # noqa: BLE001 - CV is informative, not required
                    pass

                results.append(
                    {
                        "model": name,
                        "training_time_sec": elapsed,
                        "metrics": metrics,
                        "score": score_of(metrics, classification),
                        "cv_score": cv_score,
                        "tuned": False,
                        "_pipeline": pipeline,
                    }
                )

            if request.enable_tuning and results:
                results.sort(
                    key=lambda r: (
                        r["cv_score"] if r["cv_score"] is not None else r["score"]
                    ),
                    reverse=True,
                )
                for entry in results[:2]:
                    self._tune(
                        entry,
                        candidates,
                        X_train,
                        y_train,
                        X_test,
                        y_test,
                        classification,
                        scoring,
                        preprocessor,
                    )

        return results, failures

    @staticmethod
    def _usable_folds(y, requested: int, classification: bool) -> int:
        """Cross-validation cannot use more folds than the smallest class has
        members, and never more folds than rows."""
        folds = max(2, min(requested, len(y)))
        if classification:
            smallest_class = int(pd.Series(y).value_counts().min())
            folds = max(2, min(folds, smallest_class))
        return folds

    @staticmethod
    def _tune(
        entry,
        candidates,
        X_train,
        y_train,
        X_test,
        y_test,
        classification,
        scoring,
        preprocessor=None,
    ) -> None:
        """Randomised search on a small budget; only adopted if it genuinely
        beats the untuned fit on the holdout set."""
        name = entry["model"]
        if name not in TUNING_GRIDS:
            return
        pipeline = make_pipeline(
            name,
            candidates[name],
            clone_estimator(preprocessor) if preprocessor else None,
        )
        grid = {f"model__{k}": v for k, v in TUNING_GRIDS[name].items()}
        try:
            search = RandomizedSearchCV(
                pipeline,
                grid,
                n_iter=6,
                cv=3,
                scoring=scoring,
                random_state=42,
                n_jobs=1,
            )
            search.fit(X_train, y_train)
            tuned = search.best_estimator_
            metrics = evaluate(tuned, X_test, y_test, classification)
            new_score = score_of(metrics, classification)
            if new_score >= entry["score"]:
                entry.update(
                    {
                        "metrics": metrics,
                        "score": new_score,
                        "tuned": True,
                        "_pipeline": tuned,
                        "best_params": to_jsonable(search.best_params_),
                    }
                )
        except Exception:  # noqa: BLE001 - tuning is best-effort
            return

    @staticmethod
    def _diagnostics(
        pipeline, X_test, y_test, classification: bool, label_names: list[str] | None
    ) -> dict[str, Any]:
        """Chart-ready diagnostics for the results screen: confusion matrix for
        classifiers, actual-vs-predicted and residuals for regressors."""
        try:
            preds = pipeline.predict(X_test)
        except Exception:  # noqa: BLE001
            return {}

        if classification:
            labels = sorted(
                set(np.asarray(y_test).tolist()) | set(np.asarray(preds).tolist())
            )
            matrix = confusion_matrix(y_test, preds, labels=labels)
            names = [
                label_names[i] if label_names and i < len(label_names) else str(i)
                for i in labels
            ]
            return {
                "confusion_matrix": {
                    "labels": names,
                    "matrix": [[int(v) for v in row] for row in matrix],
                }
            }

        actual = np.asarray(y_test, dtype=float)
        predicted = np.asarray(preds, dtype=float)
        residuals = actual - predicted
        # Cap the points sent to the browser - a scatter plot of 100k points is
        # unreadable and slow to render.
        limit = 500
        if actual.size > limit:
            idx = np.linspace(0, actual.size - 1, limit).astype(int)
            actual, predicted, residuals = actual[idx], predicted[idx], residuals[idx]
        return {
            "predicted_vs_actual": [
                {"actual": safe_float(a), "predicted": safe_float(p)}
                for a, p in zip(actual, predicted)
            ],
            "residuals": [
                {"predicted": safe_float(p), "residual": safe_float(r)}
                for p, r in zip(predicted, residuals)
            ],
        }

    def _persist_run(
        self,
        dataset,
        user_id,
        request,
        target,
        classification,
        best,
        results,
        features,
        rows_used,
        data_source,
    ) -> models.ModelRun | None:
        latest = (
            self.db.query(models.ModelRun)
            .filter(models.ModelRun.dataset_id == dataset.id)
            .order_by(models.ModelRun.version.desc())
            .first()
        )
        version = (latest.version + 1) if latest else 1

        model_path: str | None = None
        try:
            os.makedirs(settings.model_dir, exist_ok=True)
            model_path = os.path.join(
                settings.model_dir, f"model_{dataset.id}_v{version}.joblib"
            )
            joblib.dump(best["_pipeline"], model_path)
        except Exception:  # noqa: BLE001 - a failed dump must not fail the run
            model_path = None

        run = models.ModelRun(
            user_id=user_id,
            dataset_id=dataset.id,
            target_column=target,
            task_type="classification" if classification else "regression",
            best_model_name=best["model"],
            metrics=to_jsonable(best["metrics"]),
            model_path=model_path,
            version=version,
            config=request.model_dump(),
            features=features,
            leaderboard=[
                {
                    "model": r["model"],
                    "score": r["score"],
                    "cv_score": r["cv_score"],
                    "tuned": r["tuned"],
                    "metrics": to_jsonable(r["metrics"]),
                }
                for r in results
            ],
            data_source=data_source,
            rows_used=rows_used,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    # ------------------------------------------------------------- history
    def latest_run(self, dataset_id: int, user_id: int) -> models.ModelRun | None:
        """The most recent run. This is what /explain and /report use so they
        never trigger training as a side effect."""
        return (
            self.db.query(models.ModelRun)
            .filter(
                models.ModelRun.dataset_id == dataset_id,
                models.ModelRun.user_id == user_id,
            )
            .order_by(models.ModelRun.version.desc())
            .first()
        )

    def history(self, dataset_id: int, user_id: int) -> list[dict[str, Any]]:
        runs = (
            self.db.query(models.ModelRun)
            .filter(
                models.ModelRun.dataset_id == dataset_id,
                models.ModelRun.user_id == user_id,
            )
            .order_by(models.ModelRun.version.desc())
            .all()
        )
        return to_jsonable(
            [
                {
                    "id": r.id,
                    "version": r.version,
                    "best_model_name": r.best_model_name,
                    "task_type": r.task_type,
                    "target_column": r.target_column,
                    "metrics": r.metrics,
                    "config": r.config,
                    "features": r.features,
                    "leaderboard": r.leaderboard,
                    "data_source": r.data_source,
                    "rows_used": r.rows_used,
                    "has_model_file": bool(
                        r.model_path and os.path.exists(r.model_path)
                    ),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in runs
            ]
        )

    def load_persisted_model(self, run: models.ModelRun):
        """Rehydrate a trained pipeline from disk."""
        if not run.model_path or not os.path.exists(run.model_path):
            raise NotFoundError(
                "The saved model file for this run is missing. Re-train to regenerate it.",
                error_code="model_file_missing",
            )
        try:
            return joblib.load(run.model_path)
        except Exception as exc:  # noqa: BLE001
            raise ValidationAppError(
                "The saved model could not be loaded. Re-train to regenerate it.",
                error_code="model_load_failed",
                status_code=400,
            ) from exc
