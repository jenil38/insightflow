"""
Guided Analysis route (formerly "Agent"). Pipeline logic lives in
services/agent_service.py.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from . import auth, models
from .database import get_db
from .deps import get_owned_dataset
from .services.agent_service import AgentService

router = APIRouter(prefix="/datasets", tags=["guided-analysis"])


@router.post("/{dataset_id}/agent/run")
def run_guided_analysis(
    apply_cleaning: bool = Query(
        default=True, description="Apply the recommended cleaning plan."
    ),
    train: bool = Query(default=True, description="Train models as part of the run."),
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Run profile -> quality -> clean -> analytics -> train -> explain -> summarise.

    Runs synchronously; the response returns when the pipeline finishes. Each
    step carries its real measured duration and outcome, and a step that cannot
    run is marked skipped rather than aborting the remaining steps.
    """
    return AgentService(db).run(
        dataset, current_user.id, apply_cleaning=apply_cleaning, train=train
    )
