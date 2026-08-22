"""Per-user resource limits.

Checked before expensive operations (upload, train, report, chat) so a
single user cannot exhaust shared resources.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from .config import settings
from .exceptions import RateLimitedError, ValidationAppError


def check_dataset_count(db: Session, user_id: int) -> None:
    count = db.query(func.count(models.Dataset.id)).filter(
        models.Dataset.owner_id == user_id
    ).scalar() or 0
    if count >= settings.MAX_DATASETS_PER_USER:
        raise ValidationAppError(
            f"You have reached the limit of {settings.MAX_DATASETS_PER_USER} datasets. "
            "Delete unused datasets to upload more.",
            error_code="dataset_limit_reached",
            status_code=429,
        )


def check_storage_limit(db: Session, user_id: int, new_bytes: int) -> None:
    used = db.query(func.coalesce(func.sum(models.Dataset.size_bytes), 0)).filter(
        models.Dataset.owner_id == user_id
    ).scalar()
    limit = settings.MAX_STORAGE_PER_USER_MB * 1024 * 1024
    if used + new_bytes > limit:
        raise ValidationAppError(
            f"Adding this file would exceed your {settings.MAX_STORAGE_PER_USER_MB}MB storage limit.",
            error_code="storage_limit_reached",
            status_code=429,
        )


def check_training_rate(db: Session, user_id: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    count = db.query(func.count(models.ModelRun.id)).filter(
        models.ModelRun.user_id == user_id,
        models.ModelRun.created_at > cutoff,
    ).scalar() or 0
    if count >= settings.MAX_TRAINING_JOBS_PER_HOUR:
        raise RateLimitedError(
            f"You can run up to {settings.MAX_TRAINING_JOBS_PER_HOUR} training jobs per hour.",
            error_code="training_rate_limited",
        )


def check_report_rate(db: Session, user_id: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    count = db.query(func.count(models.ReportRecord.id)).filter(
        models.ReportRecord.user_id == user_id,
        models.ReportRecord.created_at > cutoff,
    ).scalar() or 0
    if count >= settings.MAX_REPORTS_PER_HOUR:
        raise RateLimitedError(
            f"You can generate up to {settings.MAX_REPORTS_PER_HOUR} reports per hour.",
            error_code="report_rate_limited",
        )


def check_copilot_rate(db: Session, user_id: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    count = db.query(func.count(models.ChatMessage.id)).filter(
        models.ChatMessage.user_id == user_id,
        models.ChatMessage.role == "user",
        models.ChatMessage.created_at > cutoff,
    ).scalar() or 0
    if count >= settings.MAX_COPILOT_MESSAGES_PER_HOUR:
        raise RateLimitedError(
            f"You can send up to {settings.MAX_COPILOT_MESSAGES_PER_HOUR} Copilot messages per hour.",
            error_code="copilot_rate_limited",
        )
