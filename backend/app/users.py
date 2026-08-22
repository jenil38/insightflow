"""
User-scoped routes.

`/users/me/summary` exists specifically so the home dashboard never has to read
the global `/metrics` endpoint, whose totals belong to all users combined.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .database import get_db
from .services.dataset_service import DatasetService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/summary", response_model=schemas.UserSummary)
def my_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Totals across the authenticated user's own datasets only."""
    return DatasetService(db).user_summary(current_user.id)
