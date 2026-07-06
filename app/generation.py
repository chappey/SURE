"""Generate weekly quizzes via configurable LLM providers."""

from __future__ import annotations

import logging

from app.llm.catalog import ModelEntry, get_default_model_id, resolve_model
from app.llm.errors import format_llm_error
from app.llm.registry import generate_json as provider_generate_json
from app.schemas import WeeklyQuiz, validate_questions

logger = logging.getLogger(__name__)

# Re-export for backward compatibility with api.py
format_gemini_error = format_llm_error


def _build_prompt(
    week_name: str,
    material_text: str,
    num_mc: int,
    num_tf: int,
    num_matching: int,
    mc_options: int,
    matching_pairs: int,
    include_answer_feedback: bool,
) -> str:
    requirements = []
    total_qs = num_mc + num_tf + num_matching
    mc_options = max(2, mc_options)
    matching_pairs = max(3, matching_pairs)

    requirements.append(f"- The quiz MUST have exactly {total_qs} questions in total.")

    if num_mc > 0:
        requirements.append(
            f"- Generate exactly {num_mc} multiple_choice_question items. Each multiple_choice_question must have exactly {mc_options} answer options (one correct with answer_weight=100, the remaining {mc_options - 1} incorrect with answer_weight=0)."
        )
    if num_tf > 0:
        requirements.append(
            f"- Generate exactly {num_tf} true_false_question items. Each true_false_question must have exactly 2 answer options (one correct with answer_weight=100, one incorrect with answer_weight=0)."
        )
    if num_matching > 0:
        requirements.append(
            f"- Generate exactly {num_matching} matching_question items. For matching_question, the answers list must represent pairs to match. Each answer object in the list must have: "
            f"1) answer_text: the left-side text, "
            f"2) answer_match_left: the left-side text (exactly the same as answer_text), "
            f"3) answer_match_right: the correct matching right-side text. "
            f"Provide at least {matching_pairs} matching pairs per matching question."
        )

    req_str = "\n".join(requirements)

    if include_answer_feedback:
        feedback_guideline = (
            "- correct_comments: one short sentence, grounded in the material, reinforcing why the correct answer is right.\n"
            "- incorrect_comments: one short sentence pointing students toward the relevant concept so they can self-correct.\n"
        )
    else:
        feedback_guideline = (
            "- correct_comments and incorrect_comments: leave both as empty strings.\n"
        )

    return f"""You are an expert instructional designer for an introductory Computer Science Principles course.

Generate a weekly quiz based ONLY on the course material below.

Week/Module: {week_name}

Quiz Generation Requirements:
{req_str}

General Guidelines:
- Test conceptual understanding, not trivial memorization or trick questions.
- Each question must be answerable from the provided material; do not invent facts.
- question_name: short label (e.g. "Q1: Binary representation").
- question_text: clear question stem (may include simple HTML like <p> tags).
{feedback_guideline}- quiz_title: concise title like "{week_name} Quiz".

Course material:
{material_text}
"""


def generate_weekly_quiz(
    week_name: str,
    material_text: str,
    num_mc: int = 5,
    num_tf: int = 0,
    num_matching: int = 0,
    points_per_q: int = 1,
    points_by_type: dict[str, int] | None = None,
    mc_options: int = 4,
    matching_pairs: int = 4,
    include_answer_feedback: bool = False,
    model_id: str | None = None,
) -> tuple[WeeklyQuiz, ModelEntry]:
    """Generate a quiz using the selected model from the catalog."""
    entry = resolve_model(model_id or get_default_model_id())

    prompt = _build_prompt(
        week_name=week_name,
        material_text=material_text,
        num_mc=num_mc,
        num_tf=num_tf,
        num_matching=num_matching,
        mc_options=mc_options,
        matching_pairs=matching_pairs,
        include_answer_feedback=include_answer_feedback,
    )

    logger.info("Generating quiz via %s (%s / %s)", entry.label, entry.provider, entry.model)
    schema = WeeklyQuiz.model_json_schema()
    text = provider_generate_json(entry, prompt, schema)

    quiz = WeeklyQuiz.model_validate_json(text)
    validate_questions(quiz)

    # Enforce per-type points server-side; never trust the LLM for point values.
    points_by_type = points_by_type or {}
    for q in quiz.questions:
        q.points_possible = points_by_type.get(q.question_type, points_per_q)
        q.feedback_enabled = True  # instructor-controlled, never LLM-decided
        if not include_answer_feedback:
            q.correct_comments = ""
            q.incorrect_comments = ""

    return quiz, entry
