"""Per-question agentic feedback: meta questions, LLM comments, submission processing."""

from __future__ import annotations

import logging
from typing import Any

from app.llm.catalog import resolve_model
from app.llm.fallback import fallback_models, generate_text_with_fallback
from app.llm.registry import generate_text
from app.schemas import GeneratedAnswer, GeneratedQuestion

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


def build_agentic_meta_questions(
    canvas_question_number: int,
    *,
    content_stem: str = "",
) -> list[GeneratedQuestion]:
    """Ungraded confidence + explanation questions for one content Canvas item.

    ``canvas_question_number`` is the Classic Quizzes position of the *parent*
    content question (what students see as "Question N"), not the generative
    draft index or ``question_name``.

    ``content_stem`` is accepted for API compatibility but not shown to students.
    """
    del content_stem  # numbering is enough; do not restate the parent stem
    n = int(canvas_question_number)
    banner = _FEEDBACK_BANNER.format(n=n)
    name_label = f"Question {n}"
    parent_ref = f"<strong>{name_label}</strong>"
    return [
        GeneratedQuestion(
            question_name=f"{AGENTIC_PREFIX} {name_label} — Confidence",
            question_text=(
                f"{banner}"
                f"<p>How confident were you in your answer to {parent_ref}?</p>"
            ),
            question_type="multiple_choice_question",
            points_possible=0,
            # Weight 100 on every option: any choice is "correct" (0 pts),
            # so Canvas never shows a red X — there is no wrong answer.
            answers=[
                GeneratedAnswer(answer_text=label, answer_weight=100)
                for label in CONFIDENCE_LABELS
            ],
        ),
        GeneratedQuestion(
            question_name=f"{AGENTIC_PREFIX} {name_label} — Explanation",
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
            f"{a.get('answer_text', '')} → {a.get('answer_match_right', '')}"
            for a in answers
        ]
        return "; ".join(pairs)
    for a in answers:
        if a.get("answer_weight") == 100:
            return str(a.get("answer_text", ""))
    return ""


def build_feedback_prompt(
    *,
    question_text: str,
    correct_answer: str,
    student_answer: str,
    is_correct: bool,
    confidence: str,
    explanation: str,
) -> str:
    outcome = "correct" if is_correct else "incorrect"
    answered = bool(student_answer)

    tone_rules: list[str] = []
    if confidence:
        tone_rules.append(
            f"- Calibrate tone to their confidence rating ({confidence!r}).\n"
            "  • High confidence + correct: affirm and optionally extend their understanding.\n"
            "  • High confidence + incorrect: respect their confidence; gently correct without condescension.\n"
            "  • Low confidence + correct: celebrate; encourage them to trust their reasoning.\n"
            "  • Low confidence + incorrect: be warm and supportive; scaffold from what they wrote."
        )
    else:
        tone_rules.append(
            "- The student did not rate their confidence. Use a warm, neutral tone."
        )

    if explanation:
        tone_rules.append(
            "- Reference their explanation directly — quote or paraphrase it. Do not give generic feedback."
        )
    else:
        tone_rules.append(
            "- The student left the explanation blank. Do NOT reference or invent an explanation. "
            "Base feedback on their answer alone, and gently encourage them to jot down their "
            "reasoning next time — it helps them learn and helps you help them."
        )

    if not answered:
        tone_rules.append(
            "- The student did not answer this question. Acknowledge it kindly, briefly explain "
            "the key concept, and encourage attempting every question — even a guess with "
            "reasoning is valuable."
        )
    elif not is_correct:
        tone_rules.append(
            "- Guide toward the right concept without simply revealing the answer verbatim."
        )

    rules = "\n".join(tone_rules)

    return f"""You are a supportive computer science instructor writing brief quiz feedback.

Write 2–4 sentences of personalized feedback for this student. The feedback will appear when their quiz is graded in Canvas.

Rules:
{rules}
- Use plain text only (no HTML, no markdown, no bullet lists).
- Do not mention "confidence rating" or "meta question" explicitly.

Question: {question_text}

Correct answer: {correct_answer}
Student's answer: {student_answer or "(no answer)"}
Result: {outcome if answered else "not answered"}
Student's confidence: {confidence or "Not provided"}
Student's explanation: {explanation or "Not provided"}

Feedback:"""


def generate_question_feedback(
    *,
    question_text: str,
    correct_answer: str,
    student_answer: str,
    is_correct: bool,
    confidence: str,
    explanation: str,
    model_id: str | None = None,
) -> str:
    """Call the LLM to produce one personalized comment.

    When ``model_id`` is None, the system tries all available models in catalog
    order (fallback queue). When a specific ``model_id`` is given, only that
    model is used.
    """
    prompt = build_feedback_prompt(
        question_text=question_text,
        correct_answer=correct_answer,
        student_answer=student_answer,
        is_correct=is_correct,
        confidence=confidence,
        explanation=explanation,
    )

    if model_id is None:
        models = fallback_models(requested_id=None)
        text, _entry = generate_text_with_fallback(models, prompt)
    else:
        entry = resolve_model(model_id)
        text = generate_text(entry, prompt).strip()

    if not text:
        raise RuntimeError("LLM returned empty feedback")
    return text


def build_submission_question_payload(
    submission_data: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
    content_questions: list[dict[str, Any]],
    *,
    model_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return Canvas question_id → {comment, score} entries for one submission.

    Content questions get an AI comment; explanation essays get score 0 so they
    stop showing as "needs grading" in Canvas. Mapping rows without meta question
    IDs (per-question feedback disabled) are skipped.
    """
    by_id = _answer_by_question_id(submission_data)
    payload: dict[str, dict[str, Any]] = {}

    for row in mapping:
        conf_qid = row.get("confidence_canvas_id")
        expl_qid = row.get("explanation_canvas_id")
        if not conf_qid or not expl_qid:
            continue

        content_index = row["content_index"]
        content_qid = int(row["content_canvas_id"])
        if content_index >= len(content_questions):
            continue

        content_q = content_questions[content_index]
        content_item = by_id.get(content_qid)
        confidence = _response_text(by_id.get(int(conf_qid)))
        explanation = _response_text(by_id.get(int(expl_qid)))
        student_answer = _response_text(content_item)
        correct = _is_correct(content_item, content_q)

        comment = generate_question_feedback(
            question_text=str(content_q.get("question_text", "")),
            correct_answer=_correct_answer_text(content_q),
            student_answer=student_answer,
            is_correct=correct,
            confidence=confidence,
            explanation=explanation,
            model_id=model_id,
        )
        payload[str(content_qid)] = {"comment": comment}
        # Ungraded essay: score 0 clears the "needs grading" flag.
        payload[str(int(expl_qid))] = {"score": 0}

    return payload
