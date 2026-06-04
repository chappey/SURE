"""Deploy generated quizzes to Canvas."""

from __future__ import annotations

import logging

from quiz_schema import WeeklyQuiz, to_canvas_question

log = logging.getLogger(__name__)


def find_module_by_name(course, module_name: str):
    for module in course.get_modules():
        if module.name == module_name:
            return module
    available = [m.name for m in course.get_modules()]
    raise ValueError(
        f"Canvas module {module_name!r} not found in course {course.id}. "
        f"Available modules: {', '.join(available[:20])}..."
    )


def deploy_quiz_to_canvas(course, module_name: str, payload: WeeklyQuiz):
    """Create draft quiz, add questions, and link in the week module."""
    quiz = course.create_quiz(
        quiz={
            "title": payload.quiz_title,
            "quiz_type": "assignment",
            "published": False,
            "allowed_attempts": 1,
        }
    )
    log.info("Created quiz id=%s: %s", quiz.id, quiz.title)

    for q in payload.questions:
        quiz.create_question(question=to_canvas_question(q))
        log.info("  Added question: %s", q.question_name)

    module = find_module_by_name(course, module_name)
    module.create_module_item(
        {
            "type": "Quiz",
            "content_id": quiz.id,
            "title": payload.quiz_title,
        }
    )
    log.info("Linked quiz to module: %s", module_name)

    return quiz
