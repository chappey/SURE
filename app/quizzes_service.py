"""Quiz overview, stats sync, and publish helpers."""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.agentic_feedback import generate_batched_feedback
from app.canvas_courses import (
    count_eligible_quiz_submissions,
    fetch_quiz_answer_maps,
    fetch_quiz_statistics,
    fetch_quiz_submissions_with_answers,
    get_canvas_quiz,
    update_quiz_submission_comments,
)
from app.quiz_statistics import parse_quiz_statistics
from app.storage import (
    _STORE_LOCK,
    delete_quiz_draft,
    get_quiz_draft,
    list_quizzes,
    update_quiz_draft,
)

logger = logging.getLogger(__name__)

_OVERVIEW_MAX_WORKERS = 6


def _quiz_status(deployed: bool, published: bool) -> str:
    if published:
        return "published"
    if deployed:
        return "deployed"
    return "draft"


def _ensure_quiz_url(summary: dict[str, Any], course_id: int) -> dict[str, Any]:
    from app import config

    canvas_quiz_id = summary.get("canvas_quiz_id")
    if canvas_quiz_id:
        summary["quiz_url"] = config.canvas_quiz_url(course_id, canvas_quiz_id)
    return summary


def _fetch_canvas_quiz_meta(course, canvas_quiz_id: int) -> dict[str, Any]:
    """Fetch live Canvas quiz publish state (no disk cache)."""
    cq = get_canvas_quiz(course, canvas_quiz_id)
    return {
        "published": bool(getattr(cq, "published", False)),
        "question_count": getattr(cq, "question_count", None),
    }


def _sync_deployed_quiz_summary(course, course_id: int | str, summary: dict[str, Any]) -> dict[str, Any]:
    """Refresh publish meta and live submission count for one deployed quiz."""
    canvas_quiz_id = summary.get("canvas_quiz_id") or summary.get("quiz_id")
    if not canvas_quiz_id:
        summary["status"] = _quiz_status(summary.get("deployed", False), False)
        return summary

    quiz_id_int = int(canvas_quiz_id)
    summary["canvas_quiz_id"] = quiz_id_int

    try:
        meta = _fetch_canvas_quiz_meta(course, quiz_id_int)
        published = bool(meta.get("published", False))
        summary["published"] = published
        summary["question_count"] = meta.get("question_count") or summary.get("questions_count")
        summary["status"] = _quiz_status(True, published)
    except Exception as exc:
        logger.warning("Could not sync Canvas quiz %s: %s", canvas_quiz_id, exc)
        summary["status"] = _quiz_status(summary.get("deployed", False), summary.get("published", False))

    try:
        sub_n = count_eligible_quiz_submissions(course, quiz_id_int)
        summary["submission_count"] = sub_n
        feedback_done = int(summary.get("feedback_done") or 0)
        summary["feedback_pending"] = max(0, sub_n - feedback_done)
    except Exception as exc:
        logger.warning("Could not count submissions for quiz %s: %s", canvas_quiz_id, exc)

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
        summaries.append(entry)

    deployed = [s for s in summaries if s.get("canvas_quiz_id")]
    if deployed:
        with ThreadPoolExecutor(max_workers=min(_OVERVIEW_MAX_WORKERS, len(deployed))) as pool:
            list(pool.map(lambda s: _sync_deployed_quiz_summary(course, course_id, s), deployed))

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
    """Return live submission count plus optional Canvas question analytics.

    Submission count comes from quiz submissions (includes pending_review).
    Canvas statistics are used only for hardest-question / score fields.
    """
    try:
        submission_count = count_eligible_quiz_submissions(course, canvas_quiz_id)
    except Exception as exc:
        logger.warning("Could not count submissions for quiz %s: %s", canvas_quiz_id, exc)
        return {"canvas_quiz_id": canvas_quiz_id, "available": False}

    result: dict[str, Any] = {
        "canvas_quiz_id": canvas_quiz_id,
        "available": True,
        "submission_count": submission_count,
        "generated_at": None,
        "score_average": None,
        "score_high": None,
        "score_low": None,
        "score_stdev": None,
        "score_median": None,
        "grade_distribution": {
            "mastery_count": 0,
            "proficient_count": 0,
            "developing_count": 0,
            "struggling_count": 0,
            "pass_rate": 0.0,
        },
        "questions": [],
        "topic_mastery": [],
    }

    raw = fetch_quiz_statistics(canvas, course_id, canvas_quiz_id)
    parsed = parse_quiz_statistics(raw)
    if parsed:
        result["generated_at"] = parsed.get("generated_at")
        result["score_average"] = parsed.get("score_average")
        result["score_high"] = parsed.get("score_high")
        result["score_low"] = parsed.get("score_low")
        result["score_stdev"] = parsed.get("score_stdev")
        result["score_median"] = parsed.get("score_median")
        result["grade_distribution"] = parsed.get("grade_distribution") or result["grade_distribution"]
        result["questions"] = parsed.get("questions", [])
        result["topic_mastery"] = _build_topic_mastery(result["questions"])

    return result


def _build_topic_mastery(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group question performance by topic keywords or question names."""
    topics: dict[str, dict[str, int]] = {}
    for q in questions:
        name = str(q.get("question_name") or "").strip()
        topic = "General Knowledge"
        if ":" in name:
            topic = name.split(":")[0].strip()
        elif "[" in name and "]" in name:
            topic = name.split("]")[0].replace("[", "").strip()
        elif name:
            topic = name

        if topic not in topics:
            topics[topic] = {"total_responses": 0, "correct_responses": 0, "question_count": 0}

        resp = int(q.get("responses") or 0)
        corr = int(q.get("correct_count") or 0)
        topics[topic]["total_responses"] += resp
        topics[topic]["correct_responses"] += corr
        topics[topic]["question_count"] += 1

    result = []
    for topic_name, data in topics.items():
        tot = data["total_responses"]
        corr = data["correct_responses"]
        pct = round((corr / tot * 100.0), 1) if tot > 0 else 0.0
        result.append({
            "topic": topic_name,
            "question_count": data["question_count"],
            "responses": tot,
            "correct_count": corr,
            "accuracy_pct": pct,
        })
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
    answer_maps = fetch_quiz_answer_maps(course, int(canvas_quiz_id))

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
            answer_maps=answer_maps,
            source_text=(draft.get("source_text") or None),
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


def delete_question_from_draft(
    course_id: int | str,
    quiz_id: str,
    question_index: int,
    user_name: str = "Instructor",
    course=None,
) -> dict[str, Any]:
    """Delete a question at question_index from a quiz draft atomically.

    Enforces minimum 1 question remaining, renumbers Q{n}: prefixes,
    and safely resets deployed status if currently deployed with 0 submissions.
    """
    with _STORE_LOCK:
        draft = get_quiz_draft(course_id, quiz_id)
        if not draft:
            raise KeyError(f"Quiz draft {quiz_id} not found.")

        questions = draft.get("questions") or []
        if not (0 <= question_index < len(questions)):
            raise IndexError(f"Question index {question_index} out of range (0..{len(questions)-1}).")
        if len(questions) <= 1:
            raise ValueError("A quiz must have at least one question.")

        # Check Canvas submissions if deployed
        canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
        if draft.get("deployed") and canvas_quiz_id and course:
            from app.canvas_courses import count_eligible_quiz_submissions

            try:
                sub_count = count_eligible_quiz_submissions(course, int(canvas_quiz_id))
                if sub_count > 0:
                    raise ValueError("Cannot delete questions from a quiz with existing student submissions.")
            except ValueError:
                raise
            except Exception as exc:
                logger.warning("Could not check submissions for quiz %s: %s", canvas_quiz_id, exc)

        deleted_q = questions.pop(question_index)

        # Renumber Q{n}: prefixes if present
        for i, q in enumerate(questions):
            q_name = q.get("question_name") or ""
            m = re.match(r"^Q\d+:\s*(.*)$", q_name)
            if m:
                q["question_name"] = f"Q{i+1}: {m.group(1)}"

        patch: dict[str, Any] = {"questions": questions}
        if draft.get("deployed"):
            patch["deployed"] = False
            patch["published"] = False
            patch["canvas_quiz_id"] = None
            patch["quiz_url"] = None
            patch["agentic_feedback"] = None

        updated = update_quiz_draft(course_id, quiz_id, patch, created_by=user_name)
        return {"quiz": updated, "deleted_question": deleted_q}


def update_question_in_draft(
    course_id: int | str,
    quiz_id: str,
    question_index: int,
    question_data: dict[str, Any],
    user_name: str = "Instructor",
) -> dict[str, Any]:
    """Update question content at question_index in a quiz draft atomically."""
    with _STORE_LOCK:
        draft = get_quiz_draft(course_id, quiz_id)
        if not draft:
            raise KeyError(f"Quiz draft {quiz_id} not found.")

        questions = draft.get("questions") or []
        if not (0 <= question_index < len(questions)):
            raise IndexError(f"Question index {question_index} out of range (0..{len(questions)-1}).")

        questions[question_index] = question_data
        patch: dict[str, Any] = {"questions": questions}
        updated = update_quiz_draft(course_id, quiz_id, patch, created_by=user_name)
        return {"quiz": updated, "updated_question": question_data}


def save_full_quiz_draft(
    course_id: int | str,
    quiz_id: str,
    quiz_title: str,
    questions: list[dict[str, Any]],
    user_name: str = "Instructor",
    course=None,
) -> dict[str, Any]:
    """Save full quiz draft content (title + questions) atomically."""
    with _STORE_LOCK:
        draft = get_quiz_draft(course_id, quiz_id)
        if not draft:
            raise KeyError(f"Quiz draft {quiz_id} not found.")

        if not questions:
            raise ValueError("A quiz draft must contain at least one question.")

        canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
        if draft.get("deployed") and canvas_quiz_id and course:
            from app.canvas_courses import count_eligible_quiz_submissions

            try:
                sub_count = count_eligible_quiz_submissions(course, int(canvas_quiz_id))
                if sub_count > 0:
                    raise ValueError("Cannot modify a quiz that already has active student submissions.")
            except ValueError:
                raise
            except Exception as exc:
                logger.warning("Could not check submissions for quiz %s: %s", canvas_quiz_id, exc)

        patch: dict[str, Any] = {
            "quiz_title": quiz_title.strip() or draft.get("quiz_title", "Untitled Quiz"),
            "questions": questions,
        }
        if draft.get("deployed"):
            patch["deployed"] = False
            patch["published"] = False
            patch["canvas_quiz_id"] = None
            patch["quiz_url"] = None
            patch["agentic_feedback"] = None

        updated = update_quiz_draft(course_id, quiz_id, patch, created_by=user_name)
        return {"quiz": updated}


def delete_entire_quiz_draft(
    course_id: int | str,
    quiz_id: str,
    user_name: str = "Instructor",
    course=None,
) -> dict[str, Any]:
    """Delete an entire quiz draft from disk. Refuses if deployed with student submissions."""
    with _STORE_LOCK:
        draft = get_quiz_draft(course_id, quiz_id)
        if not draft:
            raise KeyError(f"Quiz draft {quiz_id} not found.")

        canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
        if draft.get("deployed") and canvas_quiz_id and course:
            from app.canvas_courses import count_eligible_quiz_submissions

            try:
                sub_count = count_eligible_quiz_submissions(course, int(canvas_quiz_id))
                if sub_count > 0:
                    raise ValueError("Cannot delete a quiz that already has active student submissions.")
            except ValueError:
                raise
            except Exception as exc:
                logger.warning("Could not check submissions for quiz %s: %s", canvas_quiz_id, exc)

        deleted = delete_quiz_draft(course_id, quiz_id)
        if not deleted:
            raise KeyError(f"Quiz draft {quiz_id} not found on disk.")
        return {"status": "success", "quiz_id": quiz_id}


