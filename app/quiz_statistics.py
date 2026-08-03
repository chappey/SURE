"""Parse Canvas quiz statistics API responses."""

from __future__ import annotations

from typing import Any


def parse_quiz_statistics(raw: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
    """Normalize Canvas quiz statistics into submission summary fields and analytics."""
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

    sub_count = int(submission_stats.get("unique_count") or 0)
    score_avg = submission_stats.get("score_average")
    score_high = submission_stats.get("score_high")
    score_low = submission_stats.get("score_low")
    score_stdev = submission_stats.get("score_stdev")

    # Extract score list / frequencies to calculate median & grade distribution
    scores_raw = submission_stats.get("scores")
    scores_list: list[float] = []
    if isinstance(scores_raw, dict):
        for score_str, cnt in scores_raw.items():
            try:
                s_val = float(score_str)
                c_val = int(cnt or 0)
                scores_list.extend([s_val] * c_val)
            except (ValueError, TypeError):
                pass
    elif isinstance(scores_raw, list):
        for s in scores_raw:
            try:
                scores_list.append(float(s))
            except (ValueError, TypeError):
                pass

    median_score = None
    grade_dist = {
        "mastery_count": 0,
        "proficient_count": 0,
        "developing_count": 0,
        "struggling_count": 0,
        "pass_rate": 0.0,
    }

    if scores_list:
        scores_list.sort()
        n = len(scores_list)
        if n % 2 == 1:
            median_score = round(scores_list[n // 2], 2)
        else:
            median_score = round((scores_list[n // 2 - 1] + scores_list[n // 2]) / 2.0, 2)

        max_score = float(score_high) if score_high and float(score_high) > 0 else (max(scores_list) if scores_list else 100.0)
        if max_score <= 0:
            max_score = 1.0

        pass_cnt = 0
        for s in scores_list:
            pct = (s / max_score) * 100.0
            if pct >= 90.0:
                grade_dist["mastery_count"] += 1
            elif pct >= 70.0:
                grade_dist["proficient_count"] += 1
            elif pct >= 50.0:
                grade_dist["developing_count"] += 1
            else:
                grade_dist["struggling_count"] += 1

            if pct >= 70.0:
                pass_cnt += 1

        grade_dist["pass_rate"] = round((pass_cnt / n) * 100.0, 1)

    questions = _parse_question_statistics(entry.get("question_statistics"))

    return {
        "generated_at": entry.get("generated_at"),
        "submission_count": sub_count,
        "score_average": score_avg,
        "score_high": score_high,
        "score_low": score_low,
        "score_stdev": score_stdev,
        "score_median": median_score,
        "grade_distribution": grade_dist,
        "questions": questions,
    }


def _parse_question_statistics(raw: Any) -> list[dict[str, Any]]:
    """Extract per-question correct rates and option distractor breakdown from Canvas question_statistics."""
    if not isinstance(raw, list):
        return []

    questions: list[dict[str, Any]] = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        raw_answers = q.get("answers") or []
        correct = 0
        total = q.get("responses")
        answered = 0
        parsed_answers: list[dict[str, Any]] = []

        for a in raw_answers:
            if not isinstance(a, dict):
                continue
            responses = int(a.get("responses") or 0)
            answered += responses
            is_correct = bool(a.get("correct"))
            if is_correct:
                correct += responses

            parsed_answers.append(
                {
                    "id": a.get("id"),
                    "text": str(a.get("text") or a.get("answer_text") or "").strip(),
                    "correct": is_correct,
                    "responses": responses,
                }
            )

        if total is None:
            total = answered
        total_int = int(total or 0)

        # Compute percentage for each option distractor
        for pa in parsed_answers:
            pa["percentage"] = round((pa["responses"] / total_int * 100.0), 1) if total_int > 0 else 0.0

        questions.append(
            {
                "id": q.get("id"),
                "question_name": q.get("question_name") or "",
                "question_text": q.get("question_text") or "",
                "question_type": q.get("question_type") or "",
                "responses": total_int,
                "correct_count": correct,
                "incorrect_count": max(0, total_int - correct),
                "correct_pct": round((correct / total_int * 100.0), 1) if total_int > 0 else 0.0,
                "answers": parsed_answers,
            }
        )
    return questions

