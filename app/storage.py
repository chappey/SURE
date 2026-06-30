"""On-disk store for quiz drafts and Canvas module snapshots.

Persistence contract (see .cursor/rules/05-persistence.mdc):
- ALL JSON writes go through ``write_json_atomic`` — never hand-roll ``open("w")``.
  A torn write here silently loses an instructor's quiz draft.
- Read-modify-write of a draft goes through ``update_quiz_draft`` so the
  read+write is serialized under ``_STORE_LOCK`` and cannot interleave.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from app.config import CACHE_DIR

logger = logging.getLogger(__name__)

# Serializes writes within this process. FastAPI runs sync handlers in a thread
# pool, so concurrent writes to the same file ARE possible without this.
# NOTE: process-local only — multiple workers/replicas still need shared storage
# (see .cursor/rules/04-lti-canvas.mdc scaling landmine).
_STORE_LOCK = threading.RLock()


def write_json_atomic(path: Path, data: Any) -> None:
    """Atomically write ``data`` as JSON to ``path``.

    Writes to a temp file on the same filesystem, fsyncs, then ``os.replace``s
    into place — so a crash mid-write can never leave a truncated/corrupt file.
    The only sanctioned way to persist JSON in this app.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def get_course_dir(course_id: str | int) -> Path:
    """Return the course cache directory, creating it if needed."""
    path = CACHE_DIR / "courses" / str(course_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _quiz_path(course_id: str | int, quiz_id: str) -> Path:
    return get_course_dir(course_id) / "quizzes" / f"{quiz_id}.json"


def save_quiz_draft(
    course_id: str | int,
    quiz_id: str,
    quiz_data: dict[str, Any],
    created_by: str = "Instructor",
) -> None:
    """Save a generated quiz draft to disk.

    Does not mutate ``quiz_data``; writes a copy so callers can keep using their object.
    """
    record = dict(quiz_data)
    record["created_by"] = created_by
    record.setdefault("created_at", time.time())

    with _STORE_LOCK:
        write_json_atomic(_quiz_path(course_id, quiz_id), record)


def update_quiz_draft(
    course_id: str | int,
    quiz_id: str,
    patch: dict[str, Any],
    created_by: str | None = None,
) -> dict[str, Any] | None:
    """Race-safe read-modify-write of a draft: apply ``patch`` to the latest copy.

    The read and write happen under ``_STORE_LOCK`` so two concurrent updates
    cannot clobber each other. Returns the updated record, or None if missing.
    """
    with _STORE_LOCK:
        current = get_quiz_draft(course_id, quiz_id)
        if current is None:
            return None
        current.update(patch)
        if created_by is not None:
            current["created_by"] = created_by
        current.setdefault("created_at", time.time())
        write_json_atomic(_quiz_path(course_id, quiz_id), current)
        return current


def get_quiz_draft(course_id: str | int, quiz_id: str) -> dict[str, Any] | None:
    """Load a generated quiz draft from disk."""
    file_path = _quiz_path(course_id, quiz_id)
    if not file_path.is_file():
        return None
    try:
        with file_path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read quiz draft %s: %s", file_path, exc)
        return None


def list_quizzes(course_id: str | int) -> list[dict[str, Any]]:
    """List quiz drafts for a course, newest first."""
    quizzes_dir = get_course_dir(course_id) / "quizzes"
    if not quizzes_dir.is_dir():
        return []

    quizzes: list[dict[str, Any]] = []
    for file_path in quizzes_dir.glob("*.json"):
        try:
            with file_path.open(encoding="utf-8") as f:
                data = json.load(f)
            quizzes.append(
                {
                    "id": file_path.stem,
                    "title": data.get("quiz_title", "Untitled Quiz"),
                    "questions_count": len(data.get("questions", [])),
                    "created_at": data.get("created_at", file_path.stat().st_mtime),
                    "created_by": data.get("created_by", "Instructor"),
                    "deployed": data.get("deployed", False),
                    "published": data.get("published", False),
                    "canvas_quiz_id": data.get("canvas_quiz_id") or data.get("quiz_id"),
                    "module_id": data.get("module_id"),
                    "module_name": data.get("module_name"),
                    "includes_feedback": data.get("includes_feedback", False),
                }
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable quiz file %s: %s", file_path, exc)

    quizzes.sort(key=lambda item: item["created_at"], reverse=True)
    return quizzes


def save_course_modules(course_id: str | int, modules_data: list[dict[str, Any]]) -> None:
    """Save the Canvas modules list for a course."""
    with _STORE_LOCK:
        write_json_atomic(get_course_dir(course_id) / "modules.json", modules_data)


def get_cached_modules(course_id: str | int, max_age_seconds: int = 300) -> list[dict[str, Any]] | None:
    """Return cached modules if present and not stale."""
    file_path = get_course_dir(course_id) / "modules.json"
    if not file_path.is_file():
        return None
    if time.time() - file_path.stat().st_mtime > max_age_seconds:
        return None
    try:
        with file_path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read modules cache %s: %s", file_path, exc)
        return None
