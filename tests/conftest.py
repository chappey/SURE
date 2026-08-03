from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret-key-at-least-32-chars!!")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("CANVAS_API_URL", "https://canvas.test.local")


@pytest.fixture(autouse=True)
def _cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(os.environ, "CACHE_DIR", str(tmp_path / "cache"))
    import app.config
    app.config.CACHE_DIR = tmp_path / "cache"
    monkeypatch.setattr("app.config.CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr("app.storage.CACHE_DIR", tmp_path / "cache")
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)


@pytest.fixture
def sample_content_questions() -> list[dict[str, Any]]:
    return [
        {
            "question_text": "What is the capital of France?",
            "question_type": "multiple_choice_question",
            "answers": [
                {"answer_text": "Paris", "answer_weight": 100},
                {"answer_text": "London", "answer_weight": 0},
                {"answer_text": "Berlin", "answer_weight": 0},
            ],
        },
        {
            "question_text": "Python is a compiled language.",
            "question_type": "true_false_question",
            "answers": [
                {"answer_text": "True", "answer_weight": 0},
                {"answer_text": "False", "answer_weight": 100},
            ],
        },
        {
            "question_text": "Match the following:",
            "question_type": "matching_question",
            "answers": [
                {"answer_text": "CPU", "answer_match_right": "Processes instructions"},
                {"answer_text": "RAM", "answer_match_right": "Temporary storage"},
            ],
        },
        {
            "question_text": "Explain the concept of recursion.",
            "question_type": "essay_question",
            "answers": [],
        },
    ]


@pytest.fixture
def sample_mapping() -> list[dict[str, Any]]:
    return [
        {
            "content_index": 0,
            "content_canvas_id": "100",
            "confidence_canvas_id": "101",
            "explanation_canvas_id": "102",
        },
        {
            "content_index": 1,
            "content_canvas_id": "103",
            "confidence_canvas_id": "104",
            "explanation_canvas_id": "105",
        },
        {
            "content_index": 2,
            "content_canvas_id": "106",
            "confidence_canvas_id": "107",
            "explanation_canvas_id": "108",
        },
        {
            "content_index": 3,
            "content_canvas_id": "109",
            "confidence_canvas_id": "110",
            "explanation_canvas_id": "111",
        },
    ]


@pytest.fixture
def sample_submission_data() -> list[dict[str, Any]]:
    return [
        {"question_id": 100, "text": "Paris", "correct": True},
        {"question_id": 101, "text": "Very confident"},
        {"question_id": 102, "text": "I know this from geography class."},
        {"question_id": 103, "text": "False", "correct": True},
        {"question_id": 104, "text": "Completely confident"},
        {"question_id": 105, "text": ""},
        {"question_id": 106, "answer": "CPU", "correct": True},
        {"question_id": 107, "text": "Moderately confident"},
        {"question_id": 108, "text": ""},
        {"question_id": 109, "text": "Recursion is when a function calls itself."},
        {"question_id": 110, "text": ""},
        {"question_id": 111, "text": ""},
    ]


@pytest.fixture
def sample_submissions(sample_submission_data) -> list[dict[str, Any]]:
    return [
        {
            "id": 1,
            "user_id": 10,
            "score": 3.0,
            "workflow_state": "complete",
            "attempt": 1,
            "submission_data": sample_submission_data,
        },
        {
            "id": 2,
            "user_id": 20,
            "score": 2.0,
            "workflow_state": "graded",
            "attempt": 1,
            "submission_data": [
                {"question_id": 100, "text": "London", "correct": False},
                {"question_id": 101, "text": "Slightly confident"},
                {"question_id": 102, "text": "I guessed."},
                {"question_id": 103, "text": "True", "correct": False},
                {"question_id": 104, "text": "Not at all confident"},
                {"question_id": 105, "text": ""},
                {"question_id": 106, "answer": "RAM", "correct": False},
                {"question_id": 107, "text": ""},
                {"question_id": 108, "text": ""},
                {"question_id": 109, "text": ""},
                {"question_id": 110, "text": ""},
                {"question_id": 111, "text": ""},
            ],
        },
    ]


@pytest.fixture
def sample_draft(sample_content_questions, sample_mapping) -> dict[str, Any]:
    return {
        "id": "quiz-123",
        "quiz_title": "Test Quiz",
        "includes_agentic_feedback": True,
        "canvas_quiz_id": "42",
        "module_id": "7",
        "module_name": "Week 1",
        "model_id": None,
        "questions": sample_content_questions,
        "agentic_feedback": {
            "questions": sample_mapping,
        },
        "agentic_feedback_processed": {},
        "agentic_feedback_last_run": None,
    }


@pytest.fixture
def sample_batch_feedback_items() -> list:
    from app.schemas import BatchFeedbackItem
    return [
        BatchFeedbackItem(submission_id=1, question_index=1, feedback="Great job on the capital question!"),
        BatchFeedbackItem(submission_id=1, question_index=2, feedback="You correctly identified that Python is interpreted."),
        BatchFeedbackItem(submission_id=1, question_index=3, feedback="Good matching work."),
        BatchFeedbackItem(submission_id=1, question_index=4, feedback="Nice explanation of recursion."),
        BatchFeedbackItem(submission_id=2, question_index=1, feedback="Review your world capitals."),
        BatchFeedbackItem(submission_id=2, question_index=2, feedback="Python is interpreted, not compiled."),
        BatchFeedbackItem(submission_id=2, question_index=3, feedback="Try again on matching."),
        BatchFeedbackItem(submission_id=2, question_index=4, feedback="Keep practicing explanations."),
    ]


@pytest.fixture
def ai_models_json(tmp_path: Path) -> Path:
    data = [
        {"id": "model-a", "label": "Model A", "provider": "gemini", "model": "gemini-a", "default": True},
        {"id": "model-b", "label": "Model B", "provider": "openrouter", "model": "openrouter-b"},
        {"id": "model-c", "label": "Model C", "provider": "openrouter", "model": "openrouter-c"},
    ]
    path = tmp_path / "ai_models.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
