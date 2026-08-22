"""
Cleaning routes: recommend a plan, preview it, apply it, or revert it.

`clean_dataframe` is re-exported for backward compatibility (agent.py and
report.py historically imported it from here).
"""
import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import models, schemas
from .core.config import settings
from .database import get_db
from .deps import get_owned_dataset
from .services.cleaning_service import (  # noqa: F401 - re-exported
    clean_dataframe,
    cleaning_service,
)
from .services.dataframe_io import cleaned_path_for, load_dataset, write_dataframe

router = APIRouter(prefix="/datasets", tags=["cleaning"])


@router.get("/{dataset_id}/clean/plan")
def cleaning_plan(dataset: models.Dataset = Depends(get_owned_dataset)):
    """A suggested cleaning configuration, with the reasons behind each choice,
    so the UI can pre-select only what this dataset actually needs."""
    loaded = load_dataset(dataset, prefer="original", max_rows=settings.PROFILE_SAMPLE_ROWS)
    plan = cleaning_service.recommend_config(loaded.df)
    plan["has_cleaned_version"] = bool(
        dataset.cleaned_path and os.path.exists(dataset.cleaned_path)
    )
    return plan


@router.post("/{dataset_id}/clean/preview")
def preview_cleaning(
    body: schemas.CleaningRequest | None = None,
    dataset: models.Dataset = Depends(get_owned_dataset),
):
    """Compute the full effect of a cleaning config without writing anything."""
    config = (body or schemas.CleaningRequest()).config
    loaded = load_dataset(dataset, prefer="original", max_rows=settings.PROFILE_SAMPLE_ROWS)
    return cleaning_service.preview(loaded.df, config)


@router.post("/{dataset_id}/clean/apply")
def apply_cleaning(
    body: schemas.CleaningRequest | None = None,
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
):
    """Apply a cleaning config, writing a separate cleaned file.

    The original upload is never modified, which is what makes /clean/revert a
    safe operation rather than a destructive one.
    """
    config = (body or schemas.CleaningRequest()).config
    loaded = load_dataset(dataset, prefer="original")
    cleaned_df, report = cleaning_service.apply_config(loaded.df, config)

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    target_path = cleaned_path_for(dataset)
    write_dataframe(cleaned_df, target_path)

    dataset.cleaned_path = target_path
    dataset.cleaning_log = report.get("steps", [])
    db.commit()

    report["data_source"] = "cleaned"
    report["reverted"] = False
    return report


@router.post("/{dataset_id}/clean")
def clean_dataset(
    body: schemas.CleaningRequest | None = None,
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
):
    """Original endpoint, preserved. With no body it applies the default config,
    which is what the previous version did (minus the silent lower-casing)."""
    return apply_cleaning(body=body, dataset=dataset, db=db)


@router.get("/{dataset_id}/clean/log")
def cleaning_log(
    dataset: models.Dataset = Depends(get_owned_dataset),
):
    """Return the cleaning audit log for this dataset."""
    return {
        "has_cleaned_version": bool(
            dataset.cleaned_path and os.path.exists(dataset.cleaned_path)
        ),
        "cleaning_log": dataset.cleaning_log or [],
    }


@router.post("/{dataset_id}/clean/revert")
def revert_cleaning(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
):
    """Discard the cleaned copy and go back to the original upload."""
    had_cleaned = bool(dataset.cleaned_path)
    if dataset.cleaned_path and os.path.exists(dataset.cleaned_path):
        try:
            os.remove(dataset.cleaned_path)
        except OSError:
            # A stale path shouldn't block the user from reverting.
            pass
    dataset.cleaned_path = None
    db.commit()
    return {
        "reverted": had_cleaned,
        "data_source": "original",
        "detail": (
            "Reverted to the original uploaded data."
            if had_cleaned else "This dataset had no cleaned version; nothing to revert."
        ),
    }
