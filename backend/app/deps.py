"""
Shared FastAPI dependencies.

The ownership check lives here so it is written once and applied identically on
every dataset-scoped route. Previously each router repeated
`.filter(id == ..., owner_id == current_user.id)` by hand, which is exactly the
kind of thing that silently gets forgotten on a newly added endpoint and turns
into a cross-tenant data leak.
"""
from __future__ import annotations

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from . import auth, models
from .core.exceptions import NotFoundError
from .database import get_db


def get_owned_dataset(
    dataset_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
) -> models.Dataset:
    """Resolve a dataset that the authenticated user owns.

    Returns 404 (not 403) for a dataset owned by someone else: telling a caller
    "this exists but isn't yours" leaks the existence of other users' data.
    """
    dataset = (
        db.query(models.Dataset)
        .filter(models.Dataset.id == dataset_id, models.Dataset.owner_id == current_user.id)
        .first()
    )
    if dataset is None:
        raise NotFoundError("Dataset not found", error_code="dataset_not_found")
    return dataset
