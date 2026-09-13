"""Job status routes.

Clients poll GET /jobs/{id} after submitting an async operation. The job
manager is an in-memory store. On multi-node deployments, replace it with
a shared backend (Redis, database).
"""

from fastapi import APIRouter, Depends

from . import auth, models
from .core.exceptions import NotFoundError
from .core.jobs import job_manager

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(current_user: models.User = Depends(auth.get_current_user)):
    jobs = job_manager.list_for_user(current_user.id)
    return [j.to_dict() for j in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, current_user: models.User = Depends(auth.get_current_user)):
    job = job_manager.get(job_id, current_user.id)
    if job is None:
        raise NotFoundError("Job not found", error_code="job_not_found")
    result = job.to_dict()
    if job.status.value == "completed" and job.result is not None:
        result["result"] = job.result
    return result


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, current_user: models.User = Depends(auth.get_current_user)):
    success = job_manager.cancel(job_id, current_user.id)
    if not success:
        raise NotFoundError(
            "Job not found or cannot be cancelled (already running/completed)",
            error_code="job_not_cancellable",
        )
    return {"detail": "Job cancelled"}
