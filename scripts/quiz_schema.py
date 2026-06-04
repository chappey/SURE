"""Pydantic models for Gemini structured quiz output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GeneratedAnswer(BaseModel):
    answer_text: str
    answer_weight: int = Field(
        ..., description="100 for correct, 0 for incorrect"
    )
    answer_comments: str = ""


class GeneratedQuestion(BaseModel):
    question_name: str
    question_text: str
    question_type: Literal["multiple_choice_question", "true_false_question"]
    points_possible: int = 1
    answers: list[GeneratedAnswer]


class WeeklyQuiz(BaseModel):
    quiz_title: str
    questions: list[GeneratedQuestion] = Field(
        ..., min_length=5, max_length=5
    )


def validate_questions(quiz: WeeklyQuiz) -> None:
    """Ensure each question has exactly one correct answer."""
    for i, q in enumerate(quiz.questions, start=1):
        correct = [a for a in q.answers if a.answer_weight == 100]
        if len(correct) != 1:
            raise ValueError(
                f"Question {i} ({q.question_name!r}) must have exactly one "
                f"correct answer (answer_weight=100), got {len(correct)}."
            )
        if q.question_type == "multiple_choice_question" and len(q.answers) < 2:
            raise ValueError(
                f"Question {i} must have at least 2 answers for multiple choice."
            )
        if q.question_type == "true_false_question" and len(q.answers) != 2:
            raise ValueError(
                f"Question {i} must have exactly 2 answers for true/false."
            )


def to_canvas_question(q: GeneratedQuestion) -> dict:
    """Map generated question to canvasapi create_question payload."""
    return {
        "question_name": q.question_name,
        "question_text": q.question_text,
        "question_type": q.question_type,
        "points_possible": q.points_possible,
        "answers": [
            {
                "answer_text": a.answer_text,
                "answer_weight": a.answer_weight,
                "answer_comments": a.answer_comments,
            }
            for a in q.answers
        ],
    }
