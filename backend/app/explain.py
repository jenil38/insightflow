"""
Explainability routes.

Delegates to services/explainability_service.py, which explains the persisted
best model from the latest training run and always reports which method
produced the numbers (`method`, `fallback_used`, `fallback_reason`).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import auth, models
from .database import get_db
from .deps import get_owned_dataset

router = APIRouter(prefix="/datasets", tags=["explainability"])


@router.get("/{dataset_id}/explain")
def explain_dataset(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # Imported on first use: explanation builds on the ML service, which pulls
    # in scikit-learn (see app/ml.py).
    from .services.explainability_service import ExplainabilityService

    return ExplainabilityService(db).explain(dataset, current_user.id)
