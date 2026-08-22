"""
Report routes. PDF generation lives in services/report_service.py, which reads
persisted analysis and model results instead of retraining.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .core.limits import check_report_rate
from .database import get_db
from .deps import get_owned_dataset
from .services.report_service import ReportService

router = APIRouter(prefix="/datasets", tags=["report"])


@router.get("/{dataset_id}/report")
def generate_report(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    check_report_rate(db, current_user.id)
    payload, filename = ReportService(db).generate_pdf(dataset, current_user.id)
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{dataset_id}/report/history", response_model=list[schemas.ReportRecordOut]
)
def report_history(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return ReportService(db).report_history(dataset.id, current_user.id)
