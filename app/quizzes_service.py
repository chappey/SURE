"""Quiz overview, stats sync, and publish helpers."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.canvas_courses import (
    fetch_quiz_statistics,
    fetch_quiz_submissions,
    get_canvas_quiz,
)
from app.feedback import aggregate_feedback, is_feedback_question
from app.quiz_statistics import parse_quiz_statistics
from app.storage import get_course_dir, get_quiz_draft, list_quizzes

logger = logging.getLogger(__name__)

STATS_TTL_SECONDS = 600


def _quiz_status(deployed: bool, published: bool) -> str:
    if published:
        return "published"
    if deployed:
        return "deployed"
    return "draft"


def _stats_cache_path(course_id: int | str, canvas_quiz_id: int) -> Any:
    stats_dir = get_course_dir(course_id) / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    return stats_dir / f"{canvas_quiz_id}.json"


def get_cached_stats(course_id: int | str, canvas_quiz_id: int) -> dict[str, Any] | None:
    path = _stats_cache_path(course_id, canvas_quiz_id)
    if not path.is_file():
        return None
    if time.time() - path.stat().st_mtime > STATS_TTL_SECONDS:
        return None
    import json

    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_stats_cache(course_id: int | str, canvas_quiz_id: int, data: dict[str, Any]) -> None:
    import json

    path = _stats_cache_path(course_id, canvas_quiz_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _ensure_quiz_url(summary: dict[str, Any], course_id: int) -> dict[str, Any]:
    """Ensure overview rows always include a Canvas link when deployed."""
    from app import config

    if summary.get("quiz_url"):
        return summary
    canvas_quiz_id = summary.get("canvas_quiz_id")
    if canvas_quiz_id:
        base = config.CANVAS_API_URL.rstrip("/")
        summary["quiz_url"] = f"{base}/courses/{course_id}/quizzes/{canvas_quiz_id}"
    return summary


def _sync_canvas_quiz_meta(course, summary: dict[str, Any]) -> dict[str, Any]:
    canvas_quiz_id = summary.get("canvas_quiz_id") or summary.get("quiz_id")
    if not canvas_quiz_id:
        summary["status"] = _quiz_status(summary.get("deployed", False), False)
        return summary

    try:
        cq = get_canvas_quiz(course, int(canvas_quiz_id))
        published = bool(getattr(cq, "published", False))
        summary["published"] = published
        summary["canvas_quiz_id"] = int(canvas_quiz_id)
        summary["question_count"] = getattr(cq, "question_count", summary.get("questions_count"))
        summary["status"] = _quiz_status(True, published)
    except Exception as exc:
        logger.warning("Could not sync Canvas quiz %s: %s", canvas_quiz_id, exc)
        summary["status"] = _quiz_status(summary.get("deployed", False), summary.get("published", False))

    return summary


def build_quizzes_overview(
    course,
    canvas,
    course_id: int,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Merge local drafts with live Canvas publish state."""
    overview: list[dict[str, Any]] = []
    for row in list_quizzes(course_id):
        full = get_quiz_draft(course_id, row["id"]) or {}
        summary = {
            **row,
            "canvas_quiz_id": full.get("canvas_quiz_id") or full.get("quiz_id"),
            "module_id": full.get("module_id"),
            "module_name": full.get("module_name"),
            "includes_feedback": full.get("includes_feedback", False),
            "published": full.get("published", False),
        }
        if summary.get("canvas_quiz_id"):
            summary = _sync_canvas_quiz_meta(course, summary)
            summary = _ensure_quiz_url(summary, course_id)
            if summary.get("status") == "published":
                try:
                    stats = get_quiz_stats(course, canvas, course_id, int(summary["canvas_quiz_id"]))
                    if stats.get("available"):
                        summary["submission_count"] = stats.get("submission_count", 0)
                        summary["score_average"] = stats.get("score_average")
                except Exception as exc:
                    logger.warning("Could not load stats for quiz %s: %s", summary["canvas_quiz_id"], exc)
        else:
            summary["status"] = _quiz_status(summary.get("deployed", False), False)

        summary = _ensure_quiz_url(summary, course_id)

        if status_filter and summary.get("status") != status_filter:
            continue
        overview.append(summary)
    return overview


def get_quiz_stats(course, canvas, course_id: int, canvas_quiz_id: int) -> dict[str, Any]:
    """Return cached or fresh quiz statistics from Canvas."""
    cached = get_cached_stats(course_id, canvas_quiz_id)
    if cached:
        return cached

    raw = fetch_quiz_statistics(canvas, course_id, canvas_quiz_id)
    parsed = parse_quiz_statistics(raw)
    if not parsed:
        return {"canvas_quiz_id": canvas_quiz_id, "available": False}

    result = {
        "canvas_quiz_id": canvas_quiz_id,
        "available": True,
        "generated_at": parsed.get("generated_at"),
        "submission_count": parsed.get("submission_count", 0),
        "score_average": parsed.get("score_average"),
        "score_high": parsed.get("score_high"),
        "score_low": parsed.get("score_low"),
        "score_stdev": parsed.get("score_stdev"),
    }
    save_stats_cache(course_id, canvas_quiz_id, result)
    return result


def get_quiz_feedback_summary(course, canvas_quiz_id: int) -> dict[str, Any]:
    """Aggregate feedback Likert responses from Canvas submissions."""
    from app.canvas_courses import fetch_quiz_questions

    questions = fetch_quiz_questions(course, canvas_quiz_id)
    feedback_questions = [q for q in questions if is_feedback_question(str(q.get("question_name", "")))]
    if not feedback_questions:
        return {"canvas_quiz_id": canvas_quiz_id, "has_feedback": False, "questions": []}

    submissions = fetch_quiz_submissions(course, canvas_quiz_id)
    aggregated = aggregate_feedback(questions, submissions)
    return {
        "canvas_quiz_id": canvas_quiz_id,
        "has_feedback": True,
        "questions": aggregated,
    }
