"""
Profiling and data-quality routes.

The heavy lifting moved to services/profiling_service.py. `guess_target_column`
and `profile_dataframe` are re-exported here because chat.py, dashboard.py,
ml.py and explain.py historically imported them from this module.
"""
from fastapi import APIRouter, Depends

from . import models
from .core.config import settings
from .deps import get_owned_dataset
from .services.dataframe_io import load_dataset
from .services.profiling_service import (  # noqa: F401 - re-exported for backward compatibility
    guess_target_column,
    profile_dataframe,
    profiling_service,
    recommend_targets,
)

router = APIRouter(prefix="/datasets", tags=["analysis"])


@router.get("/{dataset_id}/profile")
def profile_dataset(dataset: models.Dataset = Depends(get_owned_dataset)):
    """Flat dataset profile. Response shape unchanged from the original API."""
    loaded = load_dataset(dataset, max_rows=settings.PROFILE_SAMPLE_ROWS)
    size = dataset.size_bytes or 0
    return profile_dataframe(loaded.df, size)


@router.get("/{dataset_id}/quality")
def quality_report(dataset: models.Dataset = Depends(get_owned_dataset)):
    """Full data-quality report: explainable scores, per-column profiles,
    correlations, warnings, recommended actions, and a data dictionary."""
    loaded = load_dataset(dataset, max_rows=settings.PROFILE_SAMPLE_ROWS)
    return profiling_service.full_profile(
        loaded.df,
        size_bytes=dataset.size_bytes or 0,
        source=loaded.source,
        sampled=loaded.sampled,
        total_rows=loaded.total_rows,
    )


@router.get("/{dataset_id}/target-candidates")
def target_candidates(dataset: models.Dataset = Depends(get_owned_dataset)):
    """Ranked prediction targets, each with a stated reason and confidence."""
    loaded = load_dataset(dataset, max_rows=settings.PROFILE_SAMPLE_ROWS)
    return {"candidates": recommend_targets(loaded.df, limit=8), "data_source": loaded.source}
