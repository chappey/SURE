"""Feedback Review Workspace: parse Canvas submissions and persist drafts."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.agentic_feedback import (
    _answer_by_question_id,
    _is_correct,
    generate_batched_feedback,
    html_to_plain_text,
    resolve_response_label,
)
from app.canvas_courses import (
    fetch_course_user_names,
    fetch_quiz_answer_maps,
    fetch_quiz_submissions_with_answers,
    get_canvas_quiz,
)
from app.storage import update_quiz_draft

logger = logging.getLogger(__name__)

_ELIGIBLE = frozenset({"complete", "graded", "pending_review", None})


def content_canvas_ids_from_draft(draft: dict[str, Any]) -> set[int]:
    """Canvas question ids for content (non-agentic) items."""
    mapping = (draft.get("agentic_feedback") or {}).get("questions") or []
    ids: set[int] = set()
    for row in mapping:
        cid = row.get("content_canvas_id")
        if cid is not None:
            try:
                ids.add(int(cid))
            except (TypeError, ValueError):
                pass
    return ids


def is_meta_question_stat(q: dict[str, Any], content_ids: set[int] | None = None) -> bool:
    """True if a Canvas statistics row is an agentic meta question."""
    qid = q.get("id")
    if content_ids is not None and qid is not None:
        try:
            if int(qid) in content_ids:
                return False
            if content_ids:
                # Known mapping: anything not in content set is meta
                return True
        except (TypeError, ValueError):
            pass
    name = str(q.get("question_name") or "")
    text = str(q.get("question_text") or "")
    if name.startswith("[Agentic]") or name.startswith("[Feedback]"):
        return True
    if "Feedback (Not Graded)" in text:
        return True
    return False


def filter_content_question_stats(
    questions: list[dict[str, Any]],
    draft: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    content_ids = content_canvas_ids_from_draft(draft or {})
    return [q for q in questions if not is_meta_question_stat(q, content_ids or None)]


def _points_possible(quiz) -> float | None:
    raw = getattr(quiz, "points_possible", None)
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def parse_submissions_for_workspace(
    *,
    draft: dict[str, Any],
    submissions: list[dict[str, Any]],
    answer_maps: dict[int, dict[str, str]],
    user_names: dict[int, str],
    points_possible: float | None,
    feedback_lookup: dict[tuple[int, int], str] | None = None,
    prior_by_sub: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build workspace submission rows; reuse prior ai_feedback when lookup misses."""
    feedback_lookup = feedback_lookup or {}
    prior_by_sub = prior_by_sub or {}
    content_questions = draft.get("questions") or []
    mapping = (draft.get("agentic_feedback") or {}).get("questions") or []
    parsed: list[dict[str, Any]] = []

    for sub in submissions:
        if sub.get("workflow_state") not in _ELIGIBLE:
            continue
        if not sub.get("submission_data"):
            continue

        sub_id = sub.get("id")
        user_id = sub.get("user_id")
        by_id = _answer_by_question_id(sub.get("submission_data") or [])
        prior = prior_by_sub.get(int(sub_id)) if sub_id is not None else None
        prior_qs = {
            int(q.get("q_index", i)): q
            for i, q in enumerate((prior or {}).get("questions") or [])
        }

        q_list = []
        for q_idx, q_item in enumerate(content_questions):
            row = next((r for r in mapping if r.get("content_index") == q_idx), None)
            if row:
                content_qid = int(row["content_canvas_id"]) if row.get("content_canvas_id") else None
                conf_qid = int(row["confidence_canvas_id"]) if row.get("confidence_canvas_id") else None
                expl_qid = int(row["explanation_canvas_id"]) if row.get("explanation_canvas_id") else None
                content_item = by_id.get(content_qid) if content_qid else None
                student_answer = resolve_response_label(
                    content_item, answer_maps.get(content_qid) if content_qid else None
                )
                is_correct = _is_correct(content_item, q_item)
                confidence = (
                    resolve_response_label(by_id.get(conf_qid), answer_maps.get(conf_qid))
                    if conf_qid
                    else ""
                )
                explanation = (
                    resolve_response_label(by_id.get(expl_qid), answer_maps.get(expl_qid))
                    if expl_qid
                    else ""
                )
            else:
                student_answer = ""
                confidence = ""
                explanation = ""
                is_correct = False

            ai_feedback = ""
            if sub_id is not None:
                ai_feedback = feedback_lookup.get((int(sub_id), q_idx + 1), "") or ""
            if not ai_feedback and q_idx in prior_qs:
                ai_feedback = str(prior_qs[q_idx].get("ai_feedback") or "")

            q_list.append({
                "q_index": q_idx,
                "question_id": q_item.get("id", q_idx),
                "question_text": html_to_plain_text(
                    q_item.get("question_text", f"Question {q_idx + 1}")
                ),
                "student_answer": student_answer,
                "confidence": confidence,
                "explanation": explanation,
                "score": 1 if is_correct else 0,
                "ai_feedback": ai_feedback,
            })

        uid_int = int(user_id) if user_id is not None else None
        display_name = (
            (user_names.get(uid_int) if uid_int is not None else None)
            or (f"Student #{user_id}" if user_id is not None else "Student")
        )
        parsed.append({
            "submission_id": sub_id,
            "user_id": user_id,
            "user_name": display_name,
            "score": sub.get("score"),
            "points_possible": points_possible,
            "questions": q_list,
        })
    return parsed


def workspace_response(
    quiz_id: str,
    draft: dict[str, Any],
    submissions: list[dict[str, Any]],
    *,
    points_possible: float | None,
    source_available: bool,
    generated_new: int = 0,
) -> dict[str, Any]:
    return {
        "quiz_id": quiz_id,
        "quiz_title": draft.get("quiz_title", "Quiz Feedback Review"),
        "canvas_quiz_id": draft.get("canvas_quiz_id") or draft.get("quiz_id"),
        "points_possible": points_possible,
        "questions": draft.get("questions") or [],
        "submissions": submissions,
        "source_available": source_available,
        "generated_new": generated_new,
        "updated_at": (draft.get("feedback_workspace") or {}).get("updated_at"),
    }


def build_or_merge_feedback_workspace(
    course,
    course_id: int,
    quiz_id: str,
    draft: dict[str, Any],
    *,
    force: bool = False,
    created_by: str = "Instructor",
) -> dict[str, Any]:
    """Load saved workspace or generate only for new/forced submissions; persist result."""
    canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
    if not canvas_quiz_id:
        raise ValueError("Quiz has not been deployed to Canvas.")

    canvas_quiz_id_int = int(canvas_quiz_id)
    quiz = get_canvas_quiz(course, canvas_quiz_id_int)
    points_possible = _points_possible(quiz)
    submissions = fetch_quiz_submissions_with_answers(course, canvas_quiz_id_int)
    answer_maps = fetch_quiz_answer_maps(course, canvas_quiz_id_int)
    user_names = fetch_course_user_names(course)

    content_questions = draft.get("questions") or []
    mapping = (draft.get("agentic_feedback") or {}).get("questions") or []
    source_text = (draft.get("source_text") or "").strip()
    source_available = bool(source_text)

    saved = draft.get("feedback_workspace") or {}
    prior_subs = list(saved.get("submissions") or [])
    prior_by_sub = {
        int(s["submission_id"]): s
        for s in prior_subs
        if s.get("submission_id") is not None
    }

    eligible = [
        s for s in submissions
        if s.get("workflow_state") in _ELIGIBLE and s.get("submission_data")
    ]
    eligible_ids = {int(s["id"]) for s in eligible if s.get("id") is not None}

    if force:
        to_generate = eligible
    else:
        to_generate = [
            s for s in eligible
            if int(s["id"]) not in prior_by_sub
            or not any(
                (q.get("ai_feedback") or "").strip()
                for q in (prior_by_sub[int(s["id"])].get("questions") or [])
            )
        ]

    feedback_lookup: dict[tuple[int, int], str] = {}
    generated_new = 0
    if to_generate:
        items = generate_batched_feedback(
            content_questions=content_questions,
            submissions=to_generate,
            mapping=mapping,
            model_id=draft.get("model_id"),
            answer_maps=answer_maps,
            source_text=source_text or None,
        )
        for item in items:
            feedback_lookup[(item.submission_id, item.question_index)] = item.feedback
        generated_new = len({int(s["id"]) for s in to_generate if s.get("id") is not None})

    # Drop prior rows for submissions no longer present
    prior_by_sub = {sid: row for sid, row in prior_by_sub.items() if sid in eligible_ids}

    parsed = parse_submissions_for_workspace(
        draft=draft,
        submissions=eligible,
        answer_maps=answer_maps,
        user_names=user_names,
        points_possible=points_possible,
        feedback_lookup=feedback_lookup,
        prior_by_sub=prior_by_sub,
    )

    workspace = {
        "updated_at": time.time(),
        "points_possible": points_possible,
        "submissions": parsed,
    }
    update_quiz_draft(
        course_id=course_id,
        quiz_id=quiz_id,
        patch={"feedback_workspace": workspace},
        created_by=created_by,
    )
    draft["feedback_workspace"] = workspace

    return workspace_response(
        quiz_id,
        draft,
        parsed,
        points_possible=points_possible,
        source_available=source_available,
        generated_new=generated_new,
    )


def save_feedback_workspace(
    course_id: int,
    quiz_id: str,
    draft: dict[str, Any],
    submissions: list[dict[str, Any]],
    *,
    created_by: str = "Instructor",
) -> dict[str, Any]:
    """Persist professor-edited workspace submissions."""
    points_possible = None
    saved = draft.get("feedback_workspace") or {}
    if saved.get("points_possible") is not None:
        points_possible = saved.get("points_possible")
    elif submissions:
        points_possible = submissions[0].get("points_possible")

    workspace = {
        "updated_at": time.time(),
        "points_possible": points_possible,
        "submissions": submissions,
    }
    update_quiz_draft(
        course_id=course_id,
        quiz_id=quiz_id,
        patch={"feedback_workspace": workspace},
        created_by=created_by,
    )
    draft["feedback_workspace"] = workspace
    return workspace_response(
        quiz_id,
        draft,
        submissions,
        points_possible=points_possible,
        source_available=bool((draft.get("source_text") or "").strip()),
        generated_new=0,
    )


def get_saved_workspace_payload(quiz_id: str, draft: dict[str, Any]) -> dict[str, Any] | None:
    saved = draft.get("feedback_workspace")
    if not saved or not isinstance(saved, dict):
        return None
    subs = saved.get("submissions")
    if not isinstance(subs, list):
        return None
    return workspace_response(
        quiz_id,
        draft,
        subs,
        points_possible=saved.get("points_possible"),
        source_available=bool((draft.get("source_text") or "").strip()),
        generated_new=0,
    )
