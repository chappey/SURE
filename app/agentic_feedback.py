"""Batched agentic feedback: one LLM call per quiz, all students × all questions."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.llm.fallback import fallback_models, generate_json_with_fallback
from app.schemas import BatchFeedbackResponse, GeneratedAnswer, GeneratedQuestion

logger = logging.getLogger(__name__)

AGENTIC_PREFIX = "[Agentic]"

CONFIDENCE_LABELS = [
    "Not at all confident",
    "Slightly confident",
    "Moderately confident",
    "Very confident",
    "Completely confident",
]

_FEEDBACK_BANNER = (
    '<p style="color:#b00020;font-weight:700;margin:0 0 0.5rem;">'
    "Question {n} Feedback (Not Graded)</p>"
)

_MAX_EXPLANATION_WORDS = 500
_MAX_PROMPT_TOKENS = 80_000


def build_agentic_meta_questions(
    canvas_question_number: int,
    *,
    content_stem: str = "",
) -> list[GeneratedQuestion]:
    del content_stem
    n = int(canvas_question_number)
    banner = _FEEDBACK_BANNER.format(n=n)
    name_label = f"Question {n}"
    parent_ref = f"<strong>{name_label}</strong>"
    return [
        GeneratedQuestion(
            question_name=f"{AGENTIC_PREFIX} {name_label} \u2014 Confidence",
            question_text=(
                f"{banner}"
                f"<p>How confident were you in your answer to {parent_ref}?</p>"
            ),
            question_type="multiple_choice_question",
            points_possible=0,
            answers=[
                GeneratedAnswer(answer_text=label, answer_weight=100)
                for label in CONFIDENCE_LABELS
            ],
        ),
        GeneratedQuestion(
            question_name=f"{AGENTIC_PREFIX} {name_label} \u2014 Explanation",
            question_text=(
                f"{banner}"
                f"<p>Briefly explain <strong>why</strong> you chose your answer "
                f"for {parent_ref}.</p>"
            ),
            question_type="essay_question",
            points_possible=0,
            answers=[],
        ),
    ]


def is_agentic_question(question_name: str) -> bool:
    return question_name.startswith(AGENTIC_PREFIX)


def _answer_by_question_id(
    submission_data: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for item in submission_data:
        qid = item.get("question_id")
        if qid is not None:
            by_id[int(qid)] = item
    return by_id


def _response_text(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    text = item.get("text")
    if text:
        return str(text).strip()
    answer = item.get("answer")
    if answer is not None and answer != "":
        return str(answer).strip()
    return ""


def _is_correct(item: dict[str, Any] | None, content_question: dict[str, Any]) -> bool:
    if not item:
        return False
    raw = item.get("correct")
    if raw is not None:
        return str(raw).lower() in ("true", "1", "yes")
    student = _response_text(item).lower()
    if not student:
        return False
    q_type = content_question.get("question_type", "")
    answers = content_question.get("answers") or []
    if q_type == "matching_question":
        return bool(student)
    correct_texts = [
        str(a.get("answer_text", "")).strip().lower()
        for a in answers
        if a.get("answer_weight") == 100
    ]
    return student in correct_texts


def _correct_answer_text(content_question: dict[str, Any]) -> str:
    q_type = content_question.get("question_type", "")
    answers = content_question.get("answers") or []
    if q_type == "matching_question":
        pairs = [
            f"{a.get('answer_text', '')} \u2192 {a.get('answer_match_right', '')}"
            for a in answers
        ]
        return "; ".join(pairs)
    for a in answers:
        if a.get("answer_weight") == 100:
            return str(a.get("answer_text", ""))
    return ""


def _truncate_words(text: str, max_words: int = _MAX_EXPLANATION_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " [truncated]"


def _build_questions_section(content_questions: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, q in enumerate(content_questions, start=1):
        lines.append(f"Q{i}: {q.get('question_text', '')}")
        lines.append(f"  Type: {q.get('question_type', '')}")
        lines.append(f"  Correct: {_correct_answer_text(q)}")
    return "\n".join(lines)


def _build_students_section(
    content_questions: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    for sub in submissions:
        sub_id = sub.get("id")
        by_id = _answer_by_question_id(sub.get("submission_data") or [])
        lines.append(f"Student (submission_id: {sub_id})")

        for q_idx, q in enumerate(content_questions, start=1):
            row = next((r for r in mapping if r.get("content_index") == q_idx - 1), None)
            if not row:
                continue
            content_qid = int(row["content_canvas_id"])
            conf_qid = int(row.get("confidence_canvas_id", 0))
            expl_qid = int(row.get("explanation_canvas_id", 0))

            content_item = by_id.get(content_qid)
            student_answer = _response_text(content_item)
            correct = _is_correct(content_item, q)
            confidence = _response_text(by_id.get(conf_qid)) if conf_qid else ""
            explanation = _truncate_words(_response_text(by_id.get(expl_qid)))

            lines.append(
                f"  Q{q_idx}: answer={json.dumps(student_answer or '(no answer)')} "
                f"| correct={'true' if correct else 'false'} "
                f"| confidence={json.dumps(confidence)} "
                f"| explanation={json.dumps(explanation)}"
            )
        lines.append("")
    return "\n".join(lines)


def build_batched_feedback_prompt(
    content_questions: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
) -> str:
    """One prompt embedding all questions and all students."""
    questions_section = _build_questions_section(content_questions)
    students_section = _build_students_section(content_questions, submissions, mapping)

    return (
        "You are a supportive computer science instructor writing brief quiz feedback.\n"
        "\n"
        "Write 2\u20134 sentences of personalized feedback for each student per question. "
        "The feedback will appear when their quiz is graded in Canvas.\n"
        "\n"
        "Rules:\n"
        "- Calibrate tone to each student\u2019s confidence rating:\n"
        "  \u2022 High confidence + correct: affirm and optionally extend their understanding.\n"
        "  \u2022 High confidence + incorrect: respect their confidence; gently correct without condescension.\n"
        "  \u2022 Low confidence + correct: celebrate; encourage them to trust their reasoning.\n"
        "  \u2022 Low confidence + incorrect: be warm and supportive; scaffold from what they wrote.\n"
        "- If a student provided an explanation, reference it directly \u2014 quote or paraphrase it.\n"
        "- If a student left the explanation blank, do NOT reference or invent one. "
        "Base feedback on their answer alone, and gently encourage them to jot down their "
        "reasoning next time.\n"
        "- If a student did not answer a question, acknowledge it kindly, briefly explain "
        "the key concept, and encourage attempting every question.\n"
        "- If a student answered incorrectly, guide toward the right concept without "
        "simply revealing the answer verbatim.\n"
        "- Use plain text only (no HTML, no markdown, no bullet lists).\n"
        '- Do not mention "confidence rating" or "meta question" explicitly.\n'
        "\n"
        "=== QUESTIONS ===\n"
        f"{questions_section}\n"
        "\n"
        "=== STUDENTS ===\n"
        f"{students_section}\n"
        "\n"
        "=== OUTPUT ===\n"
        'Return a JSON object with one key "feedbacks" containing an array of objects. '
        "Each object has:\n"
        "  - submission_id: the Canvas submission ID (integer)\n"
        "  - question_index: 1-based question number matching Q1, Q2... above (integer)\n"
        "  - feedback: 2\u20134 sentences of personalized feedback (string)\n"
        "\n"
        'Example: {"feedbacks": [{"submission_id": 12345, "question_index": 1, "feedback": "..."}]}'
    )


def _call_for_chunk(
    content_questions: list[dict[str, Any]],
    chunk: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
    model_id: str | None,
) -> list:
    if model_id is None:
        models = fallback_models(requested_id=None)
    else:
        models = fallback_models(requested_id=model_id)

    prompt = build_batched_feedback_prompt(content_questions, chunk, mapping)
    estimated_tokens = len(prompt) // 4
    logger.info(
        "Batched feedback prompt: ~%d tokens, %d questions, %d students",
        estimated_tokens,
        len(content_questions),
        len(chunk),
    )

    schema = BatchFeedbackResponse.model_json_schema()
    text, _entry = generate_json_with_fallback(models, prompt, schema)

    parsed = json.loads(text)
    response = BatchFeedbackResponse.model_validate(parsed)
    return response.feedbacks


def generate_batched_feedback(
    content_questions: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
    *,
    model_id: str | None = None,
) -> list:
    """Generate feedback for every submission \u00d7 question in one (or few) LLM calls.

    When the estimated prompt exceeds ``_MAX_PROMPT_TOKENS``, submissions are
    split across multiple calls to stay within limits.
    """
    eligible = [
        s for s in submissions
        if s.get("workflow_state") in ("complete", "graded", "pending_review", None)
        and s.get("submission_data")
    ]
    if not eligible:
        return []

    prompt = build_batched_feedback_prompt(content_questions, eligible, mapping)
    estimated = len(prompt) // 4

    if estimated <= _MAX_PROMPT_TOKENS:
        return _call_for_chunk(content_questions, eligible, mapping, model_id)

    mid = len(eligible) // 2
    logger.warning(
        "Batched prompt ~%d tokens exceeds %d; splitting %d students into 2 calls",
        estimated, _MAX_PROMPT_TOKENS, len(eligible),
    )
    results = _call_for_chunk(content_questions, eligible[:mid], mapping, model_id)
    results.extend(_call_for_chunk(content_questions, eligible[mid:], mapping, model_id))
    return results
