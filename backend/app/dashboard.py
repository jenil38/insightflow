"""
Analytics routes: the automatic dashboard, the configurable chart query
endpoint, and saved dashboard layouts.

`build_dashboard` and `safe_num` are re-exported for backward compatibility.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .core.config import settings
from .core.exceptions import NotFoundError
from .database import get_db
from .deps import get_owned_dataset
from .services.analytics_service import (  # noqa: F401 - re-exported
    analytics_service,
    build_dashboard,
    safe_num,
)
from .services.dataframe_io import load_dataset

router = APIRouter(prefix="/datasets", tags=["dashboard"])


@router.get("/{dataset_id}/dashboard")
def get_dashboard(dataset: models.Dataset = Depends(get_owned_dataset)):
    """Automatic dashboard. Response shape unchanged from the original API."""
    loaded = load_dataset(dataset, max_rows=settings.PROFILE_SAMPLE_ROWS)
    return analytics_service.auto_dashboard(loaded.df)


@router.post("/{dataset_id}/analytics/query")
def run_analytics_query(
    query: schemas.AnalyticsQuery,
    dataset: models.Dataset = Depends(get_owned_dataset),
):
    """Run one user-configured chart query.

    Statistically inappropriate combinations are rejected with an explanation
    rather than silently rendered (e.g. a pie chart over 40 categories, or a
    sum over a text column).
    """
    loaded = load_dataset(
        dataset,
        prefer="auto" if query.use_cleaned else "original",
        max_rows=settings.PROFILE_SAMPLE_ROWS,
    )
    result = analytics_service.run_query(loaded.df, query)
    result["data_source"] = loaded.source
    result["sampled"] = loaded.sampled
    return result


# ---------------------------------------------------------------------------
# Saved dashboard layouts
# ---------------------------------------------------------------------------


@router.get(
    "/{dataset_id}/dashboard-layouts", response_model=list[schemas.DashboardLayoutOut]
)
def list_layouts(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return (
        db.query(models.DashboardLayout)
        .filter(
            models.DashboardLayout.dataset_id == dataset.id,
            models.DashboardLayout.user_id == current_user.id,
        )
        .order_by(
            models.DashboardLayout.is_default.desc(),
            models.DashboardLayout.created_at.desc(),
        )
        .all()
    )


@router.post(
    "/{dataset_id}/dashboard-layouts",
    response_model=schemas.DashboardLayoutOut,
    status_code=status.HTTP_201_CREATED,
)
def create_layout(
    body: schemas.DashboardLayoutIn,
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if body.is_default:
        _clear_default(db, dataset.id, current_user.id)
    layout = models.DashboardLayout(
        dataset_id=dataset.id,
        user_id=current_user.id,
        name=body.name,
        charts=body.charts,
        is_default=body.is_default,
    )
    db.add(layout)
    db.commit()
    db.refresh(layout)
    return layout


@router.put(
    "/{dataset_id}/dashboard-layouts/{layout_id}",
    response_model=schemas.DashboardLayoutOut,
)
def update_layout(
    layout_id: int,
    body: schemas.DashboardLayoutIn,
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    layout = _get_owned_layout(db, layout_id, dataset.id, current_user.id)
    if body.is_default and not layout.is_default:
        _clear_default(db, dataset.id, current_user.id)
    layout.name = body.name
    layout.charts = body.charts
    layout.is_default = body.is_default
    db.commit()
    db.refresh(layout)
    return layout


@router.delete("/{dataset_id}/dashboard-layouts/{layout_id}")
def delete_layout(
    layout_id: int,
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    layout = _get_owned_layout(db, layout_id, dataset.id, current_user.id)
    db.delete(layout)
    db.commit()
    return {"detail": "Deleted"}


def _get_owned_layout(
    db: Session, layout_id: int, dataset_id: int, user_id: int
) -> models.DashboardLayout:
    layout = (
        db.query(models.DashboardLayout)
        .filter(
            models.DashboardLayout.id == layout_id,
            models.DashboardLayout.dataset_id == dataset_id,
            models.DashboardLayout.user_id == user_id,
        )
        .first()
    )
    if layout is None:
        raise NotFoundError("Dashboard layout not found", error_code="layout_not_found")
    return layout


def _clear_default(db: Session, dataset_id: int, user_id: int) -> None:
    """Only one layout per dataset per user can be the default."""
    db.query(models.DashboardLayout).filter(
        models.DashboardLayout.dataset_id == dataset_id,
        models.DashboardLayout.user_id == user_id,
        models.DashboardLayout.is_default.is_(True),
    ).update({"is_default": False})
