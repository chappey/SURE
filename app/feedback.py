"""End-of-quiz student survey questions (Canvas-native Likert MC)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.schemas import GeneratedAnswer, GeneratedQuestion

FEEDBACK_PREFIX = "[Feedback]"

LIKERT_LABELS = [
    "Strongly disagree",
    "Disagree",
    "Neutral",
    "Agree",
    "Strongly agree",
]


def build_feedback_questions() -> list[GeneratedQuestion]:
    """Standard ungraded Likert survey questions appended at deploy time."""
    prompts = [
        ("Clarity", "How clear were the quiz questions?"),
        ("Difficulty", "How appropriate was the difficulty level for this week's material?"),
        ("Pacing", "How well did the quiz reflect the pace of the course this week?"),
    ]
    questions: list[GeneratedQuestion] = []
    for key, text in prompts:
        questions.append(
            GeneratedQuestion(
                question_name=f"{FEEDBACK_PREFIX} {key}",
                question_text=f"<p>{text}</p>",
                question_type="multiple_choice_question",
                points_possible=0,
                # Weight 100 on every option: any choice is "correct" (0 pts),
                # so Canvas never shows a red X on an opinion question.
                answers=[
                    GeneratedAnswer(answer_text=label, answer_weight=100)
                    for label in LIKERT_LABELS
                ],
            )
        )
    return questions


def is_feedback_question(question_name: str) -> bool:
    return question_name.startswith(FEEDBACK_PREFIX)


def aggregate_feedback(
    canvas_questions: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate Likert responses for feedback-tagged Canvas questions."""
    feedback_qs = [
        q for q in canvas_questions
        if is_feedback_question(str(q.get("question_name", "")))
    ]
    if not feedback_qs:
        return []

    # Map Canvas question id -> question metadata
    q_by_id = {q["id"]: q for q in feedback_qs if "id" in q}

    # question_id -> Counter of answer texts
    counts: dict[int, Counter] = {qid: Counter() for qid in q_by_id}

    for sub in submissions:
        if sub.get("workflow_state") not in ("complete", "graded", "pending_review", None):
            continue
        for item in sub.get("submission_data") or []:
            qid = item.get("question_id")
            if qid not in counts:
                continue
            answer = item.get("text") or item.get("answer") or ""
            if answer:
                counts[qid][str(answer)] += 1

    results = []
    for qid, q in q_by_id.items():
        distribution = dict(counts[qid])
        total = sum(distribution.values())
        results.append(
            {
                "question_id": qid,
                "question_name": q.get("question_name"),
                "question_text": q.get("question_text"),
                "total_responses": total,
                "distribution": distribution,
                "likert_labels": LIKERT_LABELS,
            }
        )
    return results
