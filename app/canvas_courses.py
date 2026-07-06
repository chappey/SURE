"""Canvas course listing and quiz API helpers."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def list_teacher_courses(canvas, *, include_course_id: int | None = None) -> list[dict[str, Any]]:
    """Return active courses where the current token holder is a teacher."""
    courses = []
    seen: set[int] = set()

    for course in canvas.get_courses(
        enrollment_type="teacher",
        enrollment_state="active",
        per_page=100,
    ):
        code = getattr(course, "course_code", "") or getattr(course, "sis_course_id", "") or ""
        courses.append(
            {
                "id": course.id,
                "name": course.name,
                "course_code": code,
            }
        )
        seen.add(course.id)

    # Admin/dev tokens may not appear in teacher enrollments — include active course.
    if include_course_id and include_course_id not in seen:
        try:
            course = canvas.get_course(include_course_id)
            code = getattr(course, "course_code", "") or getattr(course, "sis_course_id", "") or ""
            courses.insert(
                0,
                {
                    "id": course.id,
                    "name": course.name,
                    "course_code": code,
                },
            )
        except Exception as exc:
            logger.warning("Could not include active course %s: %s", include_course_id, exc)

    courses.sort(key=lambda c: (c.get("name") or "").lower())
    return courses


def course_is_teacher(canvas, course_id: int) -> bool:
    """Return True if the user can teach in the given course."""
    if any(c["id"] == course_id for c in list_teacher_courses(canvas, include_course_id=course_id)):
        return True
    # Dev/admin token fallback: readable course implies access in local setups.
    try:
        canvas.get_course(course_id)
        from app import config
        from app.auth import oauth_enabled

        if config.CANVAS_API_TOKEN and not oauth_enabled():
            return True
    except Exception:
        pass
    return False


def get_canvas_quiz(course, canvas_quiz_id: int):
    """Fetch a Canvas quiz by ID."""
    return course.get_quiz(canvas_quiz_id)


def fetch_quiz_statistics(canvas, course_id: int, canvas_quiz_id: int) -> dict[str, Any] | None:
    """Fetch quiz statistics from the Canvas API."""
    try:
        requester = canvas._Canvas__requester
        response = requester.request(
            "GET",
            f"courses/{course_id}/quizzes/{canvas_quiz_id}/statistics",
        )
        if hasattr(response, "json"):
            return response.json()
        return response
    except Exception as exc:
        logger.warning("Could not fetch quiz statistics for %s: %s", canvas_quiz_id, exc)
        return None


def publish_canvas_quiz(course, canvas_quiz_id: int):
    """Publish a Canvas quiz."""
    quiz = course.get_quiz(canvas_quiz_id)
    return quiz.edit(quiz={"published": True})


def fetch_quiz_questions(course, canvas_quiz_id: int) -> list[dict[str, Any]]:
    """Return all questions for a Canvas quiz."""
    quiz = course.get_quiz(canvas_quiz_id)
    results = []
    for q in quiz.get_questions():
        if hasattr(q, "__dict__"):
            results.append(
                {
                    "id": getattr(q, "id", None),
                    "question_name": getattr(q, "question_name", ""),
                    "question_text": getattr(q, "question_text", ""),
                }
            )
        elif isinstance(q, dict):
            results.append(q)
    return results


def fetch_quiz_submissions(course, canvas_quiz_id: int) -> list[dict[str, Any]]:
    """Return quiz submission metadata (no per-question answers — Canvas omits them here)."""
    quiz = course.get_quiz(canvas_quiz_id)
    submissions = []
    for sub in quiz.get_submissions():
        submissions.append(
            {
                "id": getattr(sub, "id", None),
                "user_id": getattr(sub, "user_id", None),
                "score": getattr(sub, "score", None),
                "workflow_state": getattr(sub, "workflow_state", None),
                "attempt": getattr(sub, "attempt", 1),
            }
        )
    return submissions


def _normalize_submission_data(raw: Any) -> list[dict[str, Any]]:
    """Coerce a Canvas submission_data list into plain dicts."""
    items: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, dict):
            data = item
        elif hasattr(item, "__dict__"):
            data = vars(item)
        else:
            continue
        items.append(
            {
                "question_id": data.get("question_id"),
                "text": data.get("text") or data.get("answer"),
                "answer": data.get("answer"),
                "correct": data.get("correct"),
                "points": data.get("points"),
            }
        )
    return items


def fetch_quiz_submission_answers(course, canvas_quiz_id: int) -> dict[int, list[dict[str, Any]]]:
    """Return per-question answers keyed by Canvas user_id.

    The quiz submissions endpoint never exposes ``submission_data`` for completed
    attempts; the only API source is the assignment submissions endpoint with
    ``include[]=submission_history``.
    """
    quiz = course.get_quiz(canvas_quiz_id)
    assignment_id = getattr(quiz, "assignment_id", None)
    if not assignment_id:
        logger.warning("Quiz %s has no assignment_id; cannot fetch answers.", canvas_quiz_id)
        return {}

    assignment = course.get_assignment(int(assignment_id))
    answers_by_user: dict[int, list[dict[str, Any]]] = {}

    for sub in assignment.get_submissions(include=["submission_history"]):
        user_id = getattr(sub, "user_id", None)
        if user_id is None:
            continue
        history = getattr(sub, "submission_history", None) or []
        # Latest history entry that actually carries answers.
        submission_data: list[dict[str, Any]] = []
        for entry in reversed(history):
            data = entry.get("submission_data") if isinstance(entry, dict) else getattr(entry, "submission_data", None)
            if data:
                submission_data = _normalize_submission_data(data)
                break
        if submission_data:
            answers_by_user[int(user_id)] = submission_data

    return answers_by_user


def fetch_quiz_submissions_with_answers(course, canvas_quiz_id: int) -> list[dict[str, Any]]:
    """Join quiz submission metadata with per-question answers (matched on user_id)."""
    submissions = fetch_quiz_submissions(course, canvas_quiz_id)
    answers_by_user = fetch_quiz_submission_answers(course, canvas_quiz_id)
    for sub in submissions:
        user_id = sub.get("user_id")
        sub["submission_data"] = answers_by_user.get(int(user_id), []) if user_id is not None else []
    return submissions


def update_quiz_submission_comments(
    course,
    canvas_quiz_id: int,
    submission_id: int,
    *,
    attempt: int,
    question_payload: dict[str, dict[str, Any]],
) -> None:
    """Write per-question comments/scores on a completed quiz submission."""
    if not question_payload:
        return
    quiz = course.get_quiz(canvas_quiz_id)
    quiz_submission = quiz.get_quiz_submission(submission_id)
    quiz_submission.update_score_and_comments(
        quiz_submissions=[
            {
                "attempt": attempt,
                "questions": question_payload,
            }
        ]
    )
