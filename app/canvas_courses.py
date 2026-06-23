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
    """Return completed quiz submissions."""
    quiz = course.get_quiz(canvas_quiz_id)
    submissions = []
    for sub in quiz.get_submissions():
        submission_data = getattr(sub, "submission_data", None) or []
        if submission_data and hasattr(submission_data[0], "__dict__"):
            submission_data = [
                {
                    "question_id": getattr(item, "question_id", None),
                    "text": getattr(item, "text", None) or getattr(item, "answer", None),
                    "answer": getattr(item, "answer", None),
                }
                for item in submission_data
            ]
        submissions.append(
            {
                "id": getattr(sub, "id", None),
                "user_id": getattr(sub, "user_id", None),
                "score": getattr(sub, "score", None),
                "workflow_state": getattr(sub, "workflow_state", None),
                "submission_data": submission_data,
            }
        )
    return submissions
