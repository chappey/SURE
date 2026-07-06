"""Parse Canvas quiz statistics API responses."""

from __future__ import annotations

from typing import Any


def parse_quiz_statistics(raw: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
    """Normalize Canvas quiz statistics into submission summary fields."""
    if not raw:
        return {}

    # Some Canvas versions return a list at the top level.
    if isinstance(raw, list):
        raw = raw[0] if raw else {}

    if not isinstance(raw, dict):
        return {}

    stats = raw.get("quiz_statistics")
    entry: dict[str, Any] | None = None

    if isinstance(stats, list):
        entry = stats[0] if stats else None
    elif isinstance(stats, dict):
        entry = stats

    if not entry:
        # Flat response shape
        if "submission_statistics" in raw:
            entry = raw
        else:
            return {}

    submission_stats = entry.get("submission_statistics") or {}
    if not isinstance(submission_stats, dict):
        return {}

    return {
        "generated_at": entry.get("generated_at"),
        "submission_count": submission_stats.get("unique_count", 0),
        "score_average": submission_stats.get("score_average"),
        "score_high": submission_stats.get("score_high"),
        "score_low": submission_stats.get("score_low"),
        "score_stdev": submission_stats.get("score_stdev"),
        "questions": _parse_question_statistics(entry.get("question_statistics")),
    }


def _parse_question_statistics(raw: Any) -> list[dict[str, Any]]:
    """Extract per-question correct rates from Canvas question_statistics."""
    if not isinstance(raw, list):
        return []

    questions: list[dict[str, Any]] = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        answers = q.get("answers") or []
        correct = 0
        total = q.get("responses")
        answered = 0
        for a in answers:
            if not isinstance(a, dict):
                continue
            responses = int(a.get("responses") or 0)
            answered += responses
            if a.get("correct"):
                correct += responses
        if total is None:
            total = answered
        questions.append(
            {
                "id": q.get("id"),
                "question_name": q.get("question_name") or "",
                "question_text": q.get("question_text") or "",
                "question_type": q.get("question_type") or "",
                "responses": int(total or 0),
                "correct_count": correct,
            }
        )
    return questions
