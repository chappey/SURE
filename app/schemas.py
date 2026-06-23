"""Pydantic models for Gemini structured quiz output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GeneratedAnswer(BaseModel):
    answer_text: str
    answer_weight: int = Field(
        0, description="100 for correct, 0 for incorrect (only for multiple choice and true/false questions)"
    )
    answer_comments: str = ""
    answer_match_left: str = Field(
        "", description="Left side of the matching pair (only for matching questions, should match answer_text)"
    )
    answer_match_right: str = Field(
        "", description="Right side of the matching pair (only for matching questions, the correct match for the left side)"
    )


class GeneratedQuestion(BaseModel):
    question_name: str
    question_text: str
    question_type: Literal[
        "multiple_choice_question", "true_false_question", "matching_question"
    ]
    points_possible: int = 1
    answers: list[GeneratedAnswer]


class WeeklyQuiz(BaseModel):
    id: str | None = None
    quiz_title: str
    questions: list[GeneratedQuestion]


class GenerateQuizRequest(BaseModel):
    module_id: str | int
    quiz_title: str
    file_ids: list[int]
    question_types: dict[str, int]
    points_per_q: int = 1
    include_feedback: bool = True
    model_id: str | None = None


class ModelInfo(BaseModel):
    id: str
    label: str
    provider: str
    default: bool = False
    structured_output: str = "native"
    available: bool = True


class DeployQuizRequest(BaseModel):
    module_id: str | int
    quiz: WeeklyQuiz
    include_feedback: bool | None = None


class SwitchCourseRequest(BaseModel):
    course_id: int


def validate_questions(quiz: WeeklyQuiz) -> None:
    """Ensure each question matches its type requirements."""
    for i, q in enumerate(quiz.questions, start=1):
        if q.question_type == "matching_question":
            if not q.answers:
                raise ValueError(
                    f"Question {i} ({q.question_name!r}) must have at least one answer pair for matching."
                )
            for a_idx, a in enumerate(q.answers, start=1):
                if not a.answer_match_right:
                    raise ValueError(
                        f"Question {i} ({q.question_name!r}) answer pair {a_idx} must have "
                        f"a valid non-empty answer_match_right."
                    )
            continue

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
    payload = {
        "question_name": q.question_name,
        "question_text": q.question_text,
        "question_type": q.question_type,
        "points_possible": q.points_possible,
    }
    
    if q.question_type == "matching_question":
        payload["answers"] = [
            {
                "answer_text": a.answer_text,
                "answer_match_left": a.answer_match_left or a.answer_text,
                "answer_match_right": a.answer_match_right,
            }
            for a in q.answers
        ]
    else:
        payload["answers"] = [
            {
                "answer_text": a.answer_text,
                "answer_weight": a.answer_weight,
                "answer_comments": a.answer_comments,
            }
            for a in q.answers
        ]
        
    return payload

