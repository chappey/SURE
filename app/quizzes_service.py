"""Quiz overview, stats sync, and publish helpers."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.agentic_feedback import generate_batched_feedback
from app.canvas_courses import (
    fetch_quiz_statistics,
    fetch_quiz_submissions_with_answers,
    get_canvas_quiz,
    update_quiz_submission_comments,
)
from app.quiz_statistics import parse_quiz_statistics
from app.storage import (
    get_course_dir,
    get_quiz_draft,
    list_quizzes,
    update_quiz_draft,
    write_json_atomic,
)

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
    from app import config

    canvas_quiz_id = summary.get("canvas_quiz_id")
    if canvas_quiz_id:
        summary["quiz_url"] = config.canvas_quiz_url(course_id, canvas_quiz_id)
    return summary


def _fetch_canvas_quiz_meta(course, course_id: int | str, canvas_quiz_id: int) -> dict[str, Any] | None:
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
    summaries: list[dict[str, Any]] = []
    for row in list_quizzes(course_id):
        full = get_quiz_draft(course_id, row["id"]) or {}
        processed = full.get("agentic_feedback_processed") or {}
        canvas_quiz_id = full.get("canvas_quiz_id") or full.get("quiz_id")
        feedback_done = len(processed) if isinstance(processed, dict) else 0
        entry: dict[str, Any] = {
            **row,
            "canvas_quiz_id": canvas_quiz_id,
            "module_id": full.get("module_id"),
            "module_name": full.get("module_name"),
            "includes_agentic_feedback": full.get(
                "includes_agentic_feedback", False
            ),
            "published": full.get("published", False),
            "feedback_done": feedback_done,
            "submission_count": None,
            "feedback_pending": None,
        }
        if canvas_quiz_id:
            try:
                cached = get_cached_stats(course_id, int(canvas_quiz_id))
                if cached and cached.get("available"):
                    sub_n = int(cached.get("submission_count") or 0)
                    entry["submission_count"] = sub_n
                    entry["feedback_pending"] = max(0, sub_n - feedback_done)
            except (TypeError, ValueError):
                pass
        summaries.append(entry)

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


def process_agentic_feedback(
    course,
    course_id: int,
    draft: dict[str, Any],
    *,
    force: bool = False,
    draft_quiz_id: str | None = None,
    max_submissions: int | None = None,
) -> dict[str, Any]:
    """Generate and write personalized comments with one batched LLM call.

    Builds a single prompt containing every question and every student answer,
    sends it to the LLM once (or a few times for very large classes), then
    writes the feedback comments to Canvas per submission.

    Checkpoints after each run so a retry won\u2019t redo finished work.
    """
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
    easylearn_quiz_id = draft_quiz_id or draft.get("id")

    # Fetch all submissions with answers
    all_submissions = fetch_quiz_submissions_with_answers(course, int(canvas_quiz_id))

    eligible_subs = [
        s for s in all_submissions
        if s.get("workflow_state") in ("complete", "graded", "pending_review", None)
        and s.get("submission_data")
    ]
    eligible = len(eligible_subs)

    # Determine which eligible submissions are new (not yet processed)
    already_processed = {str(s["id"]) for s in eligible_subs if str(s["id"]) in processed} if not force else set()
    skipped = len(already_processed)

    to_process = [s for s in eligible_subs if str(s["id"]) not in already_processed]
    if max_submissions is not None:
        to_process = to_process[:max_submissions]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if not to_process:
        logger.info("No new submissions to process for quiz %s", easylearn_quiz_id)
    else:
        feedback_items = generate_batched_feedback(
            content_questions=content_questions,
            submissions=to_process,
            mapping=mapping,
            model_id=model_id,
        )

        # Group feedback items by submission_id
        feedback_by_sub: dict[int, list] = {}
        for item in feedback_items:
            feedback_by_sub.setdefault(item.submission_id, []).append(item)

        # Write per-submission comments to Canvas
        for sub in to_process:
            sub_id = int(sub["id"])
            items = feedback_by_sub.get(sub_id, [])
            if not items:
                errors.append({"submission_id": sub_id, "error": "No feedback generated"})
                continue

            payload: dict[str, dict[str, Any]] = {}
            for item in items:
                q_idx = item.question_index - 1
                if q_idx < 0 or q_idx >= len(mapping):
                    continue
                row = mapping[q_idx]
                content_qid = row.get("content_canvas_id")
                expl_qid = row.get("explanation_canvas_id")
                if content_qid and expl_qid:
                    payload[str(content_qid)] = {"comment": item.feedback}
                    payload[str(expl_qid)] = {"score": 0}

            if not payload:
                errors.append({"submission_id": sub_id, "error": "No Canvas question IDs mapped"})
                continue

            try:
                update_quiz_submission_comments(
                    course,
                    int(canvas_quiz_id),
                    sub_id,
                    attempt=int(sub.get("attempt") or 1),
                    question_payload=payload,
                )
            except Exception as exc:
                errors.append({"submission_id": sub_id, "error": str(exc)[:300]})
                logger.warning("Failed to write feedback for submission %s: %s", sub_id, exc)
                continue

            processed[str(sub_id)] = {
                "processed_at": time.time(),
                "questions": len([k for k in payload if "comment" in (payload[k] or {})]),
                "user_id": sub.get("user_id"),
            }
            results.append({
                "submission_id": sub_id,
                "user_id": sub.get("user_id"),
                "questions": len([k for k in payload if "comment" in (payload[k] or {})]),
            })

    last_run = time.time()
    update_quiz_draft(
        course_id=course_id,
        quiz_id=str(easylearn_quiz_id),
        patch={
            "agentic_feedback_processed": processed,
            "agentic_feedback_last_run": last_run,
        },
    )

    remaining = max(0, eligible - len(processed))
    coverage_pct = round(100.0 * len(processed) / eligible, 1) if eligible else 0.0

    return {
        "canvas_quiz_id": int(canvas_quiz_id),
        "processed": len(results),
        "skipped": skipped,
        "eligible": eligible,
        "remaining": remaining,
        "coverage_pct": coverage_pct,
        "total_processed_ever": len(processed),
        "submissions": results,
        "errors": errors,
        "agentic_feedback_processed": processed,
        "agentic_feedback_last_run": last_run,
    }
