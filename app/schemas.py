"""Pydantic models for Gemini/OpenRouter structured quiz output."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

# --- HTML sanitization for deploy -------------------------------------------------
# Canvas renders question_text / *_comments_html / answer_comments as raw HTML
# to students. LLM output and professor edits flow into these fields verbatim,
# so strip active content before anything leaves for Canvas.
_SCRIPT_BLOCK_RE = re.compile(r"<\s*(script|style|iframe|object|embed)\b[^>]*>.*?<\s*/\s*\1\s*>", re.I | re.S)
_SELF_CLOSING_ACTIVE_RE = re.compile(r"<\s*(script|style|iframe|object|embed|link|meta)\b[^>]*/?>", re.I)
_EVENT_ATTR_RE = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_DANGEROUS_URL_RE = re.compile(r"(href|src)\s*=\s*(\"|')?\s*(javascript|data|vbscript):[^(\"'>\s]*", re.I)


def sanitize_canvas_html(text: str) -> str:
    """Strip scripts, event handlers, and dangerous URLs from HTML-ish text."""
    if not text:
        return ""
    cleaned = _SCRIPT_BLOCK_RE.sub("", str(text))
    cleaned = _SELF_CLOSING_ACTIVE_RE.sub("", cleaned)
    cleaned = _EVENT_ATTR_RE.sub("", cleaned)
    cleaned = _DANGEROUS_URL_RE.sub("", cleaned)
    return cleaned


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


class DraftQuestion(BaseModel):
    question_name: str
    question_text: str
    question_type: Literal[
        "multiple_choice_question",
        "true_false_question",
        "matching_question",
        "essay_question",
    ]
    points_possible: int = 1
    difficulty: Literal["easy", "medium", "hard"] = Field(
        "medium", description="Difficulty level of the question: easy, medium, or hard"
    )
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


# Alias for backward compatibility
GeneratedQuestion = DraftQuestion


class DraftQuiz(BaseModel):
    id: str | None = None
    quiz_title: str
    questions: list[DraftQuestion]


# Alias for backward compatibility
WeeklyQuiz = DraftQuiz


class GenerateQuizRequest(BaseModel):
    module_id: str | int
    quiz_title: str = Field(max_length=200)
    file_ids: list[int] = Field(max_length=50)
    question_types: dict[str, int]
    difficulty_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Target count per difficulty level: easy, medium, hard",
    )
    points_per_type: dict[str, int] = Field(default_factory=dict)
    points_per_q: int = Field(default=1, ge=1, le=100)
    mc_options: int = Field(default=4, ge=2, le=10)
    matching_pairs: int = Field(default=4, ge=2, le=20)
    include_answer_feedback: bool = False
    include_agentic_feedback: bool = False
    custom_instructions: str = Field(default="", max_length=2000)
    model_id: str | None = None



class ModelInfo(BaseModel):
    id: str
    label: str
    provider: str
    default: bool = False
    expects_free: bool = False
    structured_output: str = "native"
    available: bool = True


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    auto_model_id: str | None = None
    auto_model_label: str | None = None


class DeployQuizRequest(BaseModel):
    module_id: str | int
    quiz: DraftQuiz
    include_agentic_feedback: bool | None = None


class BatchFeedbackItem(BaseModel):
    submission_id: int
    """Canvas submission ID for the student."""
    question_index: int
    """1-based question number (Q1, Q2, ...)."""
    feedback: str
    """1–2 sentences of grounded personalized feedback."""

class BatchFeedbackResponse(BaseModel):
    feedbacks: list[BatchFeedbackItem]

class ProcessAgenticFeedbackRequest(BaseModel):
    force: bool = False


class SwitchCourseRequest(BaseModel):
    course_id: int


def validate_questions(quiz: DraftQuiz) -> None:
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


def to_canvas_question(q: DraftQuestion) -> dict:
    """Map generated question to canvasapi create_question payload.

    Every HTML-rendered field is sanitized — Canvas shows these to students.
    """
    payload = {
        "question_name": q.question_name,
        "question_text": sanitize_canvas_html(q.question_text),
        "question_type": q.question_type,
        "points_possible": q.points_possible,
    }

    if q.correct_comments:
        payload["correct_comments_html"] = sanitize_canvas_html(q.correct_comments)
    if q.incorrect_comments and q.question_type != "matching_question":
        payload["incorrect_comments_html"] = sanitize_canvas_html(q.incorrect_comments)

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
                "answer_comments": sanitize_canvas_html(a.answer_comments),
            }
            for a in q.answers
        ]
        
    return payload
