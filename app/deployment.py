"""Deploy generated quizzes to Canvas."""

from __future__ import annotations

import logging
from typing import Any

from .agentic_feedback import build_agentic_meta_questions
from .feedback import build_feedback_questions
from .schemas import GeneratedQuestion, WeeklyQuiz, to_canvas_question

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


def _question_for_deploy(q: GeneratedQuestion, *, strip_static_feedback: bool) -> GeneratedQuestion:
    if not strip_static_feedback:
        return q
    return q.model_copy(update={"correct_comments": "", "incorrect_comments": ""})


def deploy_quiz_to_canvas(
    course,
    module_id_or_name: str | int,
    payload: WeeklyQuiz,
    *,
    include_feedback: bool = False,
    include_agentic_feedback: bool = False,
) -> tuple[Any, dict[str, Any]]:
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

    agentic_rows: list[dict[str, Any]] = []
    strip_static = include_agentic_feedback

    for i, q in enumerate(payload.questions):
        deploy_q = _question_for_deploy(q, strip_static_feedback=strip_static)
        created = quiz.create_question(question=to_canvas_question(deploy_q))
        log.info("  Added question: %s", q.question_name)

        row: dict[str, Any] = {
            "content_index": i,
            "content_canvas_id": int(created.id),
        }

        if include_agentic_feedback and q.feedback_enabled:
            meta_questions = build_agentic_meta_questions(i, q.question_name)
            conf_created = quiz.create_question(
                question=to_canvas_question(meta_questions[0])
            )
            expl_created = quiz.create_question(
                question=to_canvas_question(meta_questions[1])
            )
            row["confidence_canvas_id"] = int(conf_created.id)
            row["explanation_canvas_id"] = int(expl_created.id)
            log.info("  Added agentic meta for: %s", q.question_name)

        agentic_rows.append(row)

    if include_feedback:
        for fq in build_feedback_questions():
            quiz.create_question(question=to_canvas_question(fq))
            log.info("  Added survey question: %s", fq.question_name)

    module = find_module_by_id_or_name(course, module_id_or_name)
    module.create_module_item(
        {
            "type": "Quiz",
            "content_id": quiz.id,
            "title": payload.quiz_title,
        }
    )
    log.info("Linked quiz to module: %s", module_id_or_name)

    agentic_meta = {
        "enabled": include_agentic_feedback,
        "questions": agentic_rows if include_agentic_feedback else [],
    }
    return quiz, agentic_meta
