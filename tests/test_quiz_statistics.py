from __future__ import annotations

from app.quiz_statistics import _parse_question_statistics, parse_quiz_statistics


def test_parse_quiz_statistics_empty():
    assert parse_quiz_statistics(None) == {}
    assert parse_quiz_statistics({}) == {}
    assert parse_quiz_statistics([]) == {}


def test_parse_quiz_statistics_full():
    raw_payload = {
        "quiz_statistics": [
            {
                "generated_at": "2026-08-03T12:00:00Z",
                "submission_statistics": {
                    "unique_count": 5,
                    "score_average": 82.0,
                    "score_high": 100.0,
                    "score_low": 60.0,
                    "score_stdev": 15.0,
                    "scores": {"100": 1, "90": 1, "80": 2, "60": 1},
                },
                "question_statistics": [
                    {
                        "id": 101,
                        "question_name": "Memory: Pointers",
                        "question_text": "What is a pointer in C?",
                        "question_type": "multiple_choice_question",
                        "responses": 5,
                        "answers": [
                            {"id": 1, "text": "Memory address", "correct": True, "responses": 4},
                            {"id": 2, "text": "Variable value", "correct": False, "responses": 1},
                        ],
                    }
                ],
            }
        ]
    }

    parsed = parse_quiz_statistics(raw_payload)

    assert parsed["submission_count"] == 5
    assert parsed["score_average"] == 82.0
    assert parsed["score_median"] == 80.0
    assert parsed["grade_distribution"]["pass_rate"] == 80.0  # 4 out of 5 >= 70%
    assert parsed["grade_distribution"]["mastery_count"] == 2  # 100, 90
    assert parsed["grade_distribution"]["proficient_count"] == 2  # 80, 80
    assert parsed["grade_distribution"]["developing_count"] == 1  # 60

    qs = parsed["questions"]
    assert len(qs) == 1
    assert qs[0]["id"] == 101
    assert qs[0]["responses"] == 5
    assert qs[0]["correct_count"] == 4
    assert qs[0]["incorrect_count"] == 1
    assert qs[0]["correct_pct"] == 80.0

    answers = qs[0]["answers"]
    assert len(answers) == 2
    assert answers[0]["text"] == "Memory address"
    assert answers[0]["correct"] is True
    assert answers[0]["percentage"] == 80.0
    assert answers[1]["text"] == "Variable value"
    assert answers[1]["correct"] is False
    assert answers[1]["percentage"] == 20.0
