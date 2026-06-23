"""On-disk cache for quiz drafts and Canvas module snapshots."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.config import CACHE_DIR

logger = logging.getLogger(__name__)


def get_course_dir(course_id: str | int) -> Path:
    """Return the course cache directory, creating it if needed."""
    path = CACHE_DIR / "courses" / str(course_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_quiz_draft(
    course_id: str | int,
    quiz_id: str,
    quiz_data: dict[str, Any],
    created_by: str = "Instructor",
) -> None:
    """Save a generated quiz draft to disk."""
    quizzes_dir = get_course_dir(course_id) / "quizzes"
    quizzes_dir.mkdir(parents=True, exist_ok=True)

    quiz_data["created_by"] = created_by
    if "created_at" not in quiz_data:
        quiz_data["created_at"] = time.time()

    file_path = quizzes_dir / f"{quiz_id}.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=2, ensure_ascii=False)


def get_quiz_draft(course_id: str | int, quiz_id: str) -> dict[str, Any] | None:
    """Load a generated quiz draft from disk."""
    file_path = get_course_dir(course_id) / "quizzes" / f"{quiz_id}.json"
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
                    "quiz_url": data.get("quiz_url", ""),
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
    file_path = get_course_dir(course_id) / "modules.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(modules_data, f, indent=2)


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
