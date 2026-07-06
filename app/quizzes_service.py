"""Quiz overview, stats sync, and publish helpers."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.canvas_courses import (
    fetch_quiz_statistics,
    fetch_quiz_submissions_with_answers,
    get_canvas_quiz,
    update_quiz_submission_comments,
)
from app.agentic_feedback import build_submission_question_payload
from app.feedback import aggregate_feedback, is_feedback_question
from app.quiz_statistics import parse_quiz_statistics
from app.storage import get_course_dir, get_quiz_draft, list_quizzes, write_json_atomic

logger = logging.getLogger(__name__)

STATS_TTL_SECONDS = 600
CANVAS_META_TTL_SECONDS = 60
_OVERVIEW_MAX_WORKERS = 6


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


def _read_ttl_cache(path: Any, ttl_seconds: int) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    if time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_cached_stats(course_id: int | str, canvas_quiz_id: int) -> dict[str, Any] | None:
    return _read_ttl_cache(_stats_cache_path(course_id, canvas_quiz_id), STATS_TTL_SECONDS)


def save_stats_cache(course_id: int | str, canvas_quiz_id: int, data: dict[str, Any]) -> None:
    write_json_atomic(_stats_cache_path(course_id, canvas_quiz_id), data)


def _canvas_meta_cache_path(course_id: int | str, canvas_quiz_id: int) -> Any:
    meta_dir = get_course_dir(course_id) / "canvas_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    return meta_dir / f"{canvas_quiz_id}.json"


def _ensure_quiz_url(summary: dict[str, Any], course_id: int) -> dict[str, Any]:
    """Derive the browser-facing Canvas link on read (never persisted)."""
    from app import config

    canvas_quiz_id = summary.get("canvas_quiz_id")
    if canvas_quiz_id:
        summary["quiz_url"] = config.canvas_quiz_url(course_id, canvas_quiz_id)
    return summary


def _fetch_canvas_quiz_meta(course, course_id: int | str, canvas_quiz_id: int) -> dict[str, Any] | None:
    """Return {published, question_count} for a Canvas quiz, with a short TTL cache."""
    cached = _read_ttl_cache(_canvas_meta_cache_path(course_id, canvas_quiz_id), CANVAS_META_TTL_SECONDS)
    if cached is not None:
        return cached

    cq = get_canvas_quiz(course, canvas_quiz_id)
    meta = {
        "published": bool(getattr(cq, "published", False)),
        "question_count": getattr(cq, "question_count", None),
    }
    write_json_atomic(_canvas_meta_cache_path(course_id, canvas_quiz_id), meta)
    return meta


def _sync_canvas_quiz_meta(course, course_id: int | str, summary: dict[str, Any]) -> dict[str, Any]:
    canvas_quiz_id = summary.get("canvas_quiz_id") or summary.get("quiz_id")
    if not canvas_quiz_id:
        summary["status"] = _quiz_status(summary.get("deployed", False), False)
        return summary

    try:
        meta = _fetch_canvas_quiz_meta(course, course_id, int(canvas_quiz_id))
        published = bool(meta.get("published", False)) if meta else False
        summary["published"] = published
        summary["canvas_quiz_id"] = int(canvas_quiz_id)
        summary["question_count"] = (meta or {}).get("question_count") or summary.get("questions_count")
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
    """Merge local drafts with live Canvas publish state.

    Canvas syncs run in parallel with a short TTL cache; per-quiz statistics are
    intentionally NOT fetched here (they load on demand in the detail view).
    """
    summaries: list[dict[str, Any]] = []
    for row in list_quizzes(course_id):
        full = get_quiz_draft(course_id, row["id"]) or {}
        summaries.append(
            {
                **row,
                "canvas_quiz_id": full.get("canvas_quiz_id") or full.get("quiz_id"),
                "module_id": full.get("module_id"),
                "module_name": full.get("module_name"),
                "includes_feedback": full.get("includes_feedback", False),
                "includes_agentic_feedback": full.get("includes_agentic_feedback", False),
                "published": full.get("published", False),
            }
        )

    deployed = [s for s in summaries if s.get("canvas_quiz_id")]
    if deployed:
        with ThreadPoolExecutor(max_workers=min(_OVERVIEW_MAX_WORKERS, len(deployed))) as pool:
            list(pool.map(lambda s: _sync_canvas_quiz_meta(course, course_id, s), deployed))

    overview: list[dict[str, Any]] = []
    for summary in summaries:
        if not summary.get("canvas_quiz_id"):
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
        "questions": parsed.get("questions", []),
    }
    save_stats_cache(course_id, canvas_quiz_id, result)
    return result


def get_quiz_feedback_summary(course, canvas_quiz_id: int) -> dict[str, Any]:
    """Aggregate end-of-quiz survey Likert responses from Canvas submissions."""
    from app.canvas_courses import fetch_quiz_questions

    questions = fetch_quiz_questions(course, canvas_quiz_id)
    feedback_questions = [q for q in questions if is_feedback_question(str(q.get("question_name", "")))]
    if not feedback_questions:
        return {"canvas_quiz_id": canvas_quiz_id, "has_feedback": False, "questions": []}

    submissions = fetch_quiz_submissions_with_answers(course, canvas_quiz_id)
    aggregated = aggregate_feedback(questions, submissions)
    return {
        "canvas_quiz_id": canvas_quiz_id,
        "has_feedback": True,
        "questions": aggregated,
    }


def process_agentic_feedback(
    course,
    course_id: int,
    draft: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Generate and write personalized comments for quiz submissions."""
    if not draft.get("includes_agentic_feedback"):
        raise ValueError("This quiz does not have agentic feedback enabled.")

    agentic = draft.get("agentic_feedback") or {}
    mapping = agentic.get("questions") or []
    if not mapping:
        raise ValueError(
            "No agentic question mapping found. Redeploy the quiz with agentic feedback enabled."
        )

    canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
    if not canvas_quiz_id:
        raise ValueError("Quiz has not been deployed to Canvas.")

    content_questions = draft.get("questions") or []
    model_id = draft.get("model_id")
    processed: dict[str, Any] = dict(draft.get("agentic_feedback_processed") or {})

    submissions = fetch_quiz_submissions_with_answers(course, int(canvas_quiz_id))
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped = 0

    for sub in submissions:
        state = sub.get("workflow_state")
        if state not in ("complete", "graded", "pending_review", None):
            continue

        sub_id = str(sub["id"])
        if not force and sub_id in processed:
            skipped += 1
            continue

        if not sub.get("submission_data"):
            errors.append(
                {
                    "submission_id": sub.get("id"),
                    "error": "No answer data available from Canvas for this submission.",
                }
            )
            continue

        try:
            payload = build_submission_question_payload(
                sub["submission_data"],
                mapping,
                content_questions,
                model_id=model_id,
            )
            comment_count = sum(1 for entry in payload.values() if "comment" in entry)
            if not comment_count:
                errors.append({"submission_id": sub["id"], "error": "No comments generated"})
                continue

            update_quiz_submission_comments(
                course,
                int(canvas_quiz_id),
                int(sub["id"]),
                attempt=int(sub.get("attempt") or 1),
                question_payload=payload,
            )
            processed[sub_id] = {
                "processed_at": time.time(),
                "questions": comment_count,
                "user_id": sub.get("user_id"),
            }
            results.append(
                {
                    "submission_id": sub["id"],
                    "user_id": sub.get("user_id"),
                    "questions": comment_count,
                }
            )
        except Exception as exc:
            logger.warning(
                "Agentic feedback failed for submission %s: %s", sub.get("id"), exc
            )
            errors.append({"submission_id": sub.get("id"), "error": str(exc)})

    return {
        "canvas_quiz_id": int(canvas_quiz_id),
        "processed": len(results),
        "skipped": skipped,
        "submissions": results,
        "errors": errors,
        "agentic_feedback_processed": processed,
        "agentic_feedback_last_run": time.time(),
    }
