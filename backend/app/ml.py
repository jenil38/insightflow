"""
Machine-learning routes.

The training engine moved to services/ml_service.py. It lives there because
agent.py and report.py used to call this module's route function directly, so
generating a report retrained every model and created a new model version on
each request.

`prep_features` and `is_classification` are re-exported for backward
compatibility with anything that imported them from here.
"""
import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .core.exceptions import NotFoundError
from .core.limits import check_training_rate
from .database import get_db
from .deps import get_owned_dataset
from .services.ml_service import (  # noqa: F401 - re-exported
    MLService,
    build_preprocessor,
    is_classification,
    prep_features,
)

router = APIRouter(prefix="/datasets", tags=["ml"])


@router.get("/{dataset_id}/train/options", response_model=schemas.TrainConfigOptions)
def training_options(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
):
    """Everything the pre-training configuration screen needs: real column
    names, ranked target candidates with reasons, suggested exclusions, and
    data-quality warnings."""
    return MLService(db).config_options(dataset)


@router.post("/{dataset_id}/train")
def train_models(
    body: schemas.TrainRequest | None = None,
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    check_training_rate(db, current_user.id)
    return MLService(db).train(dataset, current_user.id, body or schemas.TrainRequest())


@router.get("/{dataset_id}/model/history")
def model_history(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return MLService(db).history(dataset.id, current_user.id)


@router.get("/{dataset_id}/model/download")
def download_model(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Download the persisted best model from the latest run as a joblib file."""
    run = MLService(db).latest_run(dataset.id, current_user.id)
    if run is None:
        raise NotFoundError(
            "No trained model for this dataset yet - run training first.",
            error_code="no_trained_model",
        )
    if not run.model_path or not os.path.exists(run.model_path):
        raise NotFoundError(
            "The saved model file for the latest run is missing. Re-train to regenerate it.",
            error_code="model_file_missing",
        )
    safe_name = (run.best_model_name or "model").replace(" ", "_")
    return FileResponse(
        run.model_path,
        filename=f"{safe_name}_v{run.version}.joblib",
        media_type="application/octet-stream",
    )
