"""Generate weekly quizzes via configurable LLM providers."""

from __future__ import annotations

import logging
import time

from app import config
from app.llm.catalog import ModelEntry, resolve_model
from app.llm.providers.openrouter import last_routed_model
from app.llm.errors import format_llm_error
from app.llm.fallback import fallback_models, generate_json_with_fallback
from app.llm.registry import generate_json as provider_generate_json
from app.ops.context import llm_purpose
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
    difficulty_counts: dict[str, int] | None = None,
    professor_memories: list[str] | None = None,
    model_instructions: list[str] | None = None,
    course_name: str | None = None,
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

    if difficulty_counts:
        num_easy = difficulty_counts.get("easy", 0)
        num_med = difficulty_counts.get("medium", 0)
        num_hard = difficulty_counts.get("hard", 0)
        requirements.append(
            f"- Difficulty distribution: generate exactly {num_easy} 'easy' questions, {num_med} 'medium' questions, and {num_hard} 'hard' questions."
        )
        requirements.append(
            "- Each question MUST specify its 'difficulty' attribute as 'easy', 'medium', or 'hard' matching its intended level:\n"
            "  * easy: Basic recall of definitions, terminology, or direct facts from the text.\n"
            "  * medium: Comprehension, application of principles, analyzing mechanism behaviors, or standard tradeoffs.\n"
            "  * hard: Deep analysis, edge cases, multi-step reasoning, complex algorithm tradeoffs, or subtle distinctions."
        )

    if custom_instructions and custom_instructions.strip():
        requirements.append(
            f"- Instructor specific guidance/focus: {custom_instructions.strip()}"
        )

    if professor_memories:
        clean_mems = [m.strip() for m in professor_memories if m and m.strip()]
        if clean_mems:
            items = "\n".join(f"  * {m}" for m in clean_mems)
            requirements.append(
                f"- Professor Tastes, Terminology & Style Preferences (MUST follow strictly):\n{items}"
            )

    if model_instructions:
        clean_model_inst = [m.strip() for m in model_instructions if m and m.strip()]
        if clean_model_inst:
            items = "\n".join(f"  * {m}" for m in clean_model_inst)
            requirements.append(
                f"- Model-Specific Generation Rules (Mandatory):\n{items}"
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

    course_context = f" teaching '{course_name.strip()}'" if course_name and course_name.strip() else ""

    return f"""You are a university instructor{course_context} writing a formative quiz for students who studied ONLY the material below.

Week/Module: {week_name}

Hard requirements:
{req_str}

Grounding rules (non-negotiable):
- Use ONLY facts, definitions, mechanisms, concepts, and relationships that appear in the material.
- Do NOT invent numbers, slide counts, "N concepts", outside trivia, or facts not in the text.
- Do NOT ask meta-questions about the deck structure (e.g. "how many slides", "Concept 1.1").
- A careful student who studied this material must be able to select the keyed answer.
- Exactly ONE option has answer_weight=100; all other options answer_weight=0.
- Incorrect options must be wrong for THIS stem (no two right answers). Other true facts from elsewhere in the material must not also fully answer the question.
- Prefer testing: core definitions, fundamental mechanisms, conceptual principles, key terminology, relationships, and problem-solving application directly grounded in the text.
- Prefer paraphrases of the material over pure keyword matching when possible, but stay faithful.
- For true/false: the statement must be clearly true or false from the material alone.
- Formatting & Syntax: Write chemical formulas, exponents, and mathematical expressions using standard Unicode (e.g. sp³, H₂O, CO₂, ΔH, →, °C) or clean HTML tags (<sub>, <sup>). Do NOT use raw LaTeX enclosing tokens ($...$, $$...$$, \\( ... \\)).

Format:
- question_name: short label (e.g. "Q1: Hybridization geometry").
- question_text: clear stem (simple HTML like <p>, <sub>, <sup> is OK).
- difficulty: 'easy', 'medium', or 'hard'.
{feedback_guideline}- quiz_title: concise title like "{week_name} Quiz".

Course material (sole source of truth):
{material_text}
"""


def generate_weekly_quiz(
    week_name: str,
    material_text: str,
    num_mc: int = 4,
    num_tf: int = 2,
    num_matching: int = 0,
    difficulty_counts: dict[str, int] | None = None,
    points_per_q: int = 1,
    points_by_type: dict[str, int] | None = None,
    mc_options: int = 4,
    matching_pairs: int = 3,
    include_answer_feedback: bool = False,
    custom_instructions: str = "",
    model_id: str | None = None,
    professor_memories: list[str] | None = None,
    course_name: str | None = None,
) -> tuple[DraftQuiz, ModelEntry]:
    """Generate a quiz using the selected model from the catalog (or auto-select).

    When ``model_id`` is None, Auto uses ``openrouter/auto`` (up to two
    attempts). When a specific ``model_id`` is given, only that model is used.
    """
    from app.retrieval import select_material

    material_text = select_material(material_text, query=week_name)

    # Determine model-specific prompt instructions
    model_instructions: list[str] = []
    if model_id:
        target_entry = resolve_model(model_id)
        model_instructions = getattr(target_entry, "prompt_instructions", []) or []
    else:
        auto_models = fallback_models(requested_id=None)
        if auto_models:
            model_instructions = getattr(auto_models[0], "prompt_instructions", []) or []

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
        difficulty_counts=difficulty_counts,
        professor_memories=professor_memories,
        model_instructions=model_instructions,
        course_name=course_name,
    )


    schema = DraftQuiz.model_json_schema()
    t0 = time.perf_counter()

    def _accept_quiz_json(raw: str) -> None:
        quiz = DraftQuiz.model_validate_json(raw)
        validate_questions(quiz)

    with llm_purpose("quiz_generate"):
        if model_id is None:
            models = fallback_models(requested_id=None)
            logger.info(
                "Generating quiz: Auto mode, %d model(s) available",
                len(models),
            )
            text, entry = generate_json_with_fallback(
                models,
                prompt,
                schema,
                validate=_accept_quiz_json,
                timeout_seconds=config.AUTO_MODEL_TIMEOUT_SECONDS,
                allow_object_fallback=False,
            )
        else:
            entry = resolve_model(model_id)
            logger.info(
                "Generating quiz via %s (%s/%s)", entry.id, entry.provider, entry.model
            )
            text = provider_generate_json(entry, prompt, schema)

    if entry.model in ("openrouter/auto", "openrouter/auto-beta"):
        routed = last_routed_model()
        if routed:
            entry = entry.model_copy(
                update={"model": routed, "label": f"{entry.label} → {routed}"}
            )

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
