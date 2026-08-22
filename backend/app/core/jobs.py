"""Lightweight background job system.

Runs expensive operations (training, profiling, reports) in a thread pool so
HTTP requests return immediately with a job ID. Clients poll GET /jobs/{id}
for status. Replace with Celery/RQ for multi-node deployments.

States: queued -> running -> completed | failed | cancelled
"""
from __future__ import annotations

import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Callable


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    user_id: int
    job_type: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    progress_message: str = ""
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    dataset_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "status": self.status.value,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "dataset_id": self.dataset_id,
            "has_result": self.result is not None,
        }


class JobManager:
    def __init__(self, max_workers: int = 3):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def submit(
        self,
        user_id: int,
        job_type: str,
        fn: Callable,
        *args: Any,
        dataset_id: int | None = None,
        **kwargs: Any,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            job_type=job_type,
            dataset_id=dataset_id,
        )
        with self._lock:
            self._jobs[job.id] = job

        def _run():
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            try:
                job.result = fn(*args, progress_callback=job._update_progress, **kwargs)
                job.status = JobStatus.COMPLETED
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.completed_at = datetime.now(timezone.utc)

        def _progress_cb(pct: int, msg: str = ""):
            job.progress = pct
            job.progress_message = msg

        job._update_progress = _progress_cb
        self._executor.submit(_run)
        return job

    def get(self, job_id: str, user_id: int) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job and job.user_id == user_id:
            return job
        return None

    def list_for_user(self, user_id: int, limit: int = 20) -> list[Job]:
        with self._lock:
            user_jobs = [j for j in self._jobs.values() if j.user_id == user_id]
        user_jobs.sort(key=lambda j: j.created_at, reverse=True)
        return user_jobs[:limit]

    def cancel(self, job_id: str, user_id: int) -> bool:
        job = self.get(job_id, user_id)
        if job and job.status == JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(timezone.utc)
            return True
        return False

    def cleanup_old(self, max_age_hours: int = 24) -> int:
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta
        cutoff -= timedelta(hours=max_age_hours)
        removed = 0
        with self._lock:
            to_remove = [
                jid for jid, j in self._jobs.items()
                if j.completed_at and j.completed_at < cutoff
            ]
            for jid in to_remove:
                del self._jobs[jid]
                removed += 1
        return removed


job_manager = JobManager()
