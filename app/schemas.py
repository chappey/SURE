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
        "multiple_choice_question",
        "true_false_question",
        "matching_question",
        "essay_question",
    ]
    points_possible: int = 1
    answers: list[GeneratedAnswer]
    feedback_enabled: bool = Field(
        True,
        description="Whether AI feedback (confidence + explanation) is collected for this question",
    )
    correct_comments: str = Field(
        "", description="Short explanation shown to students who answer correctly"
    )
    incorrect_comments: str = Field(
        "", description="Short explanation shown to students who answer incorrectly"
    )


class WeeklyQuiz(BaseModel):
    id: str | None = None
    quiz_title: str
    questions: list[GeneratedQuestion]


class GenerateQuizRequest(BaseModel):
    module_id: str | int
    quiz_title: str
    file_ids: list[int]
    question_types: dict[str, int]
    points_per_type: dict[str, int] = Field(default_factory=dict)
    points_per_q: int = 1
    mc_options: int = 4
    matching_pairs: int = 4
    include_feedback: bool = True
    include_answer_feedback: bool = False
    include_agentic_feedback: bool = False
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
    include_agentic_feedback: bool | None = None


class ProcessAgenticFeedbackRequest(BaseModel):
    force: bool = False


class SwitchCourseRequest(BaseModel):
    course_id: int


class DemoSlide(BaseModel):
    """A single lecture slide: a title plus a few bullet points."""

    title: str
    bullets: list[str] = Field(default_factory=list)


class DemoModule(BaseModel):
    """A course module backed by one lecture deck."""

    name: str = Field(description="Module/week name, e.g. 'Week 1: Foundations'")
    summary: str = Field("", description="One-sentence description of the module")
    slides: list[DemoSlide]


class DemoCourse(BaseModel):
    """An AI-generated demo course outline used to populate Canvas with material."""

    course_title: str
    course_code: str = ""
    modules: list[DemoModule]


def validate_questions(quiz: WeeklyQuiz) -> None:
    """Ensure each question matches its type requirements."""
    for i, q in enumerate(quiz.questions, start=1):
        if q.question_type == "essay_question":
            continue

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

    if q.correct_comments:
        payload["correct_comments_html"] = q.correct_comments
    if q.incorrect_comments and q.question_type != "matching_question":
        payload["incorrect_comments_html"] = q.incorrect_comments

    if q.question_type == "essay_question":
        return payload

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

