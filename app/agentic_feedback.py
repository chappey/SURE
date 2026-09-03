"""Batched agentic feedback: one LLM call per quiz, all students × all questions."""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

from app.llm.fallback import fallback_models, generate_json_with_fallback
from app.ops.context import llm_purpose
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

# Labels students can pick that count as "high confidence" in analytics.
_HIGH_CONFIDENCE_LABELS = frozenset(
    {"very confident", "completely confident", "high", "4", "5"}
)


def confidence_is_high(label: str | None) -> bool:
    """True when a stored confidence label indicates high confidence.

    Tolerates case/whitespace and the short forms used by older drafts
    ("High", "4", "5"). Unknown/empty labels are NOT high confidence.
    """
    return str(label or "").strip().lower() in _HIGH_CONFIDENCE_LABELS

_FEEDBACK_BANNER = (
    '<p style="color:#b00020;font-weight:700;margin:0 0 0.5rem;">'
    "Question {n} Feedback (Not Graded)</p>"
)

_MAX_EXPLANATION_WORDS = 500
_MAX_PROMPT_TOKENS = 80_000
_TAG_RE = re.compile(r"<[^>]+>")


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


def html_to_plain_text(value: Any) -> str:
    """Strip HTML tags/entities to plain text (XSS-safe when later escaped)."""
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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


def resolve_response_label(
    item: dict[str, Any] | None,
    answer_map: dict[str, str] | None = None,
) -> str:
    """Human-readable student response: answer id → label, then strip HTML."""
    raw = _response_text(item)
    if not raw:
        return ""
    if answer_map:
        label = answer_map.get(raw) or answer_map.get(str(raw).strip())
        if label:
            return html_to_plain_text(label)
    return html_to_plain_text(raw)


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
        lines.append(f"Q{i}: {html_to_plain_text(q.get('question_text', ''))}")
        lines.append(f"  Type: {q.get('question_type', '')}")
        lines.append(f"  Correct: {_correct_answer_text(q)}")
    return "\n".join(lines)


def _build_students_section(
    content_questions: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
    answer_maps: dict[int, dict[str, str]] | None = None,
) -> str:
    answer_maps = answer_maps or {}
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
            student_answer = resolve_response_label(
                content_item, answer_maps.get(content_qid)
            )
            correct = _is_correct(content_item, q)
            confidence = (
                resolve_response_label(by_id.get(conf_qid), answer_maps.get(conf_qid))
                if conf_qid
                else ""
            )
            explanation = _truncate_words(
                resolve_response_label(by_id.get(expl_qid), answer_maps.get(expl_qid))
                if expl_qid
                else ""
            )

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
    answer_maps: dict[int, dict[str, str]] | None = None,
    source_text: str | None = None,
) -> str:
    """One prompt embedding all questions and all students."""
    questions_section = _build_questions_section(content_questions)
    students_section = _build_students_section(
        content_questions, submissions, mapping, answer_maps=answer_maps
    )
    source = (source_text or "").strip()
    source_section = source if source else "(No source material available for this quiz.)"

    return (
        "You are a computer science instructor writing brief, grounded, high-impact quiz feedback.\n"
        "\n"
        "Write 1–2 tight, constructive sentences of personalized feedback for each student per question. "
        "The feedback will appear when their quiz is graded in Canvas.\n"
        "\n"
        "Pedagogical Rules (strictly enforced):\n"
        "- NO VAGUE META-REFERENCES: Do NOT write generic phrases like 'according to the source', 'the text states', 'in the material', or 'as written'. State concrete concepts, algorithms, terms, and mechanisms directly.\n"
        "- NO FILLER OR GENERIC PRAISE: Never write 'Good job!', 'Great work!', or 'Nice try!'. Superfluous compliments waste the student's time; every sentence must deliver instructional substance.\n"
        "- WHEN CORRECT: Explain the concept from a secondary angle, elaborate on an underlying mechanism, or highlight key trade-offs (e.g. 'Correct. While heapify-down maintains parent-child invariants in O(log n) time, bottom-up construction achieves O(n) total cost').\n"
        "- WHEN INCORRECT: Direct Diagnostic — pinpoint the precise misconception, state the core mechanism from the course material, and explain why the chosen answer fails.\n"
        "- CONFIDENCE CALIBRATION: Direct and precise correction for High Confidence + Wrong to resolve illusions of competence; supportive guidance for Low Confidence; validate intuition for Low Confidence + Correct.\n"
        "- If the student wrote an explanation, you may briefly reference it; never invent one.\n"
        "- Use plain text only (no HTML, no markdown, no bullet lists).\n"
        "\n"
        "=== SOURCE MATERIAL ===\n"
        f"{source_section}\n"
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
        "  - feedback: 1–2 sentences of grounded feedback (string)\n"
        "\n"
        'Example: {"feedbacks": [{"submission_id": 12345, "question_index": 1, "feedback": "..."}]}'
    )


def _call_for_chunk(
    content_questions: list[dict[str, Any]],
    chunk: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
    model_id: str | None,
    answer_maps: dict[int, dict[str, str]] | None = None,
    source_text: str | None = None,
) -> list:
    if model_id is None:
        models = fallback_models(requested_id=None)
    else:
        models = fallback_models(requested_id=model_id)

    prompt = build_batched_feedback_prompt(
        content_questions,
        chunk,
        mapping,
        answer_maps=answer_maps,
        source_text=source_text,
    )
    estimated_tokens = len(prompt) // 4
    logger.info(
        "Batched feedback prompt: ~%d tokens, %d questions, %d students",
        estimated_tokens,
        len(content_questions),
        len(chunk),
    )

    schema = BatchFeedbackResponse.model_json_schema()
    with llm_purpose("agentic_feedback"):
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
    answer_maps: dict[int, dict[str, str]] | None = None,
    source_text: str | None = None,
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

    prompt = build_batched_feedback_prompt(
        content_questions,
        eligible,
        mapping,
        answer_maps=answer_maps,
        source_text=source_text,
    )
    estimated = len(prompt) // 4

    if estimated <= _MAX_PROMPT_TOKENS:
        return _call_for_chunk(
            content_questions,
            eligible,
            mapping,
            model_id,
            answer_maps=answer_maps,
            source_text=source_text,
        )

    mid = len(eligible) // 2
    logger.warning(
        "Batched prompt ~%d tokens exceeds %d; splitting %d students into 2 calls",
        estimated, _MAX_PROMPT_TOKENS, len(eligible),
    )
    results = _call_for_chunk(
        content_questions,
        eligible[:mid],
        mapping,
        model_id,
        answer_maps=answer_maps,
        source_text=source_text,
    )
    results.extend(
        _call_for_chunk(
            content_questions,
            eligible[mid:],
            mapping,
            model_id,
            answer_maps=answer_maps,
            source_text=source_text,
        )
    )
    return results
