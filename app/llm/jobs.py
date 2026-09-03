"""In-memory quiz-generation jobs. One process; a restart drops in-flight jobs."""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def create(job_id: str) -> dict[str, Any]:
    with _lock:
        job = {"id": job_id, "status": "pending", "created_at": time.time()}
        _jobs[job_id] = job
        return job


def set_running(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["status"] = "running"


def set_ready(job_id: str, quiz: dict[str, Any]) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["status"] = "ready"
            job["quiz"] = quiz


def set_error(job_id: str, message: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["status"] = "error"
            job["error"] = message


def get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
