"""
Dataset endpoints. Business logic lives in services/dataset_service.py; this
module stays a thin FastAPI router.

`read_dataframe` and `UPLOAD_DIR` are re-exported for backward compatibility,
since several other modules import them from here.
"""

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .core.config import settings
from .core.limits import check_dataset_count, check_storage_limit
from .database import get_db
from .deps import get_owned_dataset
from .services.dataset_service import DatasetService, read_dataframe  # noqa: F401 - re-exported

router = APIRouter(prefix="/datasets", tags=["datasets"])
UPLOAD_DIR = settings.UPLOAD_DIR  # re-exported for backward compatibility


@router.post("/upload", response_model=schemas.DatasetOut)
async def upload_dataset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    check_dataset_count(db, current_user.id)
    contents = await file.read()
    check_storage_limit(db, current_user.id, len(contents))
    service = DatasetService(db)
    return service.upload(
        owner_id=current_user.id,
        filename=file.filename,
        contents=contents,
        content_type=file.content_type,
    )


@router.get(
    "", response_model=list[schemas.DatasetOut] | schemas.Page[schemas.DatasetOut]
)
def list_datasets(
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    service = DatasetService(db)
    # Backward compatible: no `page` query param -> same plain list as before.
    if page is None:
        return service.list_all(current_user.id)
    items, total = service.list_paginated(current_user.id, page, page_size)
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    return schemas.Page(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/with-status", response_model=list[schemas.DatasetListItem])
def list_datasets_with_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Datasets plus cleaning and model status, for the datasets table."""
    return DatasetService(db).list_with_status(current_user.id)


@router.get("/{dataset_id}", response_model=schemas.DatasetDetail)
def get_dataset(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return DatasetService(db).detail(dataset, current_user.id)


@router.get("/{dataset_id}/preview", response_model=schemas.PreviewResponse)
def preview_dataset(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=settings.PREVIEW_MAX_PAGE_SIZE),
    sort_by: str | None = Query(default=None),
    sort_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
    search: str | None = Query(default=None, max_length=200),
    columns: list[str] | None = Query(default=None),
    use_cleaned: bool = Query(default=True),
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
):
    """Paginated row-level preview with sorting, search, and column selection."""
    return DatasetService(db).preview(
        dataset,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        search=search,
        columns=columns,
        use_cleaned=use_cleaned,
    )


@router.get("/{dataset_id}/columns")
def dataset_columns(
    use_cleaned: bool = Query(default=True),
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
):
    """Lightweight per-column metadata for table headers and column pickers."""
    return DatasetService(db).columns_metadata(dataset, use_cleaned=use_cleaned)


@router.get("/{dataset_id}/columns/{column}")
def dataset_column_profile(
    column: str,
    use_cleaned: bool = Query(default=True),
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
):
    """Full statistics for one column, for the column profile drawer."""
    return DatasetService(db).column_profile(dataset, column, use_cleaned=use_cleaned)


@router.get("/{dataset_id}/export")
def export_dataset(
    use_cleaned: bool = Query(default=True),
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
):
    """Download the active (cleaned or original) data as CSV."""
    payload, filename = DatasetService(db).export_csv(dataset, use_cleaned=use_cleaned)
    return Response(
        content=payload,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    DatasetService(db).delete(dataset.id, current_user.id)
    return {"detail": "Deleted"}
