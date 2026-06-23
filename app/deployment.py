"""Deploy generated quizzes to Canvas."""

from __future__ import annotations

import logging

from .feedback import build_feedback_questions
from .schemas import WeeklyQuiz, to_canvas_question

log = logging.getLogger(__name__)


def find_module_by_id_or_name(course, module_id_or_name: str | int):
    try:
        module_id = int(module_id_or_name)
        return course.get_module(module_id)
    except (ValueError, TypeError):
        pass

    for module in course.get_modules():
        if module.name == module_id_or_name:
            return module
    available = [m.name for m in course.get_modules()]
    raise ValueError(
        f"Canvas module {module_id_or_name!r} not found in course {course.id}. "
        f"Available modules: {', '.join(available[:20])}..."
    )


def deploy_quiz_to_canvas(
    course,
    module_id_or_name: str | int,
    payload: WeeklyQuiz,
    *,
    include_feedback: bool = False,
):
    """Create draft quiz, add questions, optionally append feedback items, link in module."""
    quiz = course.create_quiz(
        quiz={
            "title": payload.quiz_title,
            "quiz_type": "assignment",
            "published": False,
            "allowed_attempts": 1,
        }
    )
    log.info("Created quiz id=%s: %s", quiz.id, quiz.title)

    questions = list(payload.questions)
    if include_feedback:
        questions.extend(build_feedback_questions())

    for q in questions:
        quiz.create_question(question=to_canvas_question(q))
        log.info("  Added question: %s", q.question_name)

    module = find_module_by_id_or_name(course, module_id_or_name)
    module.create_module_item(
        {
            "type": "Quiz",
            "content_id": quiz.id,
            "title": payload.quiz_title,
        }
    )
    log.info("Linked quiz to module: %s", module_id_or_name)

    return quiz
