"""Generate weekly quizzes via configurable LLM providers."""

from __future__ import annotations

import logging
import time

from app.llm.catalog import ModelEntry, resolve_model
from app.llm.errors import format_llm_error
from app.llm.fallback import fallback_models, generate_json_with_fallback
from app.llm.registry import generate_json as provider_generate_json
from app.schemas import DraftQuiz, validate_questions

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
    custom_instructions: str = "",
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

    if custom_instructions and custom_instructions.strip():
        requirements.append(
            f"- Instructor specific guidance/focus: {custom_instructions.strip()}"
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

    return f"""You are a university CS instructor writing a formative quiz for students who studied ONLY the material below.

Week/Module: {week_name}

Hard requirements:
{req_str}

Grounding rules (non-negotiable):
- Use ONLY facts, definitions, complexities, algorithms, and mechanisms that appear in the material.
- Do NOT invent numbers, slide counts, "N concepts", outside trivia, or facts not in the text.
- Do NOT ask meta-questions about the deck structure (e.g. "how many slides", "Concept 1.1").
- A careful student who studied this material must be able to select the keyed answer.
- Exactly ONE option has answer_weight=100; all other options answer_weight=0.
- Incorrect options must be wrong for THIS stem (no two right answers). Other true facts from elsewhere in the material must not also fully answer the question.
- Prefer testing: named definitions, Big-O / costs, data-structure tradeoffs, OS mechanisms, protocol behaviors, etc.
- Prefer paraphrases of the material over pure keyword matching when possible, but stay faithful.
- For true/false: the statement must be clearly true or false from the material alone.

Format:
- question_name: short label (e.g. "Q1: Big-O upper bound").
- question_text: clear stem (simple HTML like <p> is OK).
{feedback_guideline}- quiz_title: concise title like "{week_name} Quiz".

Course material (sole source of truth):
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
    custom_instructions: str = "",
    model_id: str | None = None,
) -> tuple[DraftQuiz, ModelEntry]:
    """Generate a quiz using the selected model from the catalog (or auto-select).

    When ``model_id`` is None, the system tries all available models in catalog
    order (fallback queue). When a specific ``model_id`` is given, only that
    model is used.
    """
    from app.retrieval import select_material

    material_text = select_material(material_text, query=week_name)

    prompt = _build_prompt(
        week_name=week_name,
        material_text=material_text,
        num_mc=num_mc,
        num_tf=num_tf,
        num_matching=num_matching,
        mc_options=mc_options,
        matching_pairs=matching_pairs,
        include_answer_feedback=include_answer_feedback,
        custom_instructions=custom_instructions,
    )

    schema = DraftQuiz.model_json_schema()
    t0 = time.perf_counter()

    if model_id is None:
        models = fallback_models(requested_id=None)
        text, entry = generate_json_with_fallback(models, prompt, schema)
    else:
        entry = resolve_model(model_id)
        logger.info("Generating quiz via %s (%s / %s)", entry.label, entry.provider, entry.model)
        text = provider_generate_json(entry, prompt, schema)

    llm_ms = (time.perf_counter() - t0) * 1000

    quiz = DraftQuiz.model_validate_json(text)
    validate_questions(quiz)

    # Enforce per-type points server-side; never trust the LLM for point values.
    points_by_type = points_by_type or {}
    for q in quiz.questions:
        q.points_possible = points_by_type.get(q.question_type, points_per_q)
        q.feedback_enabled = True  # instructor-controlled, never LLM-decided
        if not include_answer_feedback:
            q.correct_comments = ""
            q.incorrect_comments = ""

    logger.info(
        "Quiz generate profile: model=%s llm_ms=%.0f prompt_chars=%s questions=%s",
        entry.id,
        llm_ms,
        len(material_text),
        len(quiz.questions),
    )
    return quiz, entry
