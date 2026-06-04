"""Generate weekly quizzes via Google Gemini structured output."""

from __future__ import annotations

import os

import config  # noqa: F401 — loads PROJECT_ROOT/.env

from google import genai
from google.genai import types

from quiz_schema import WeeklyQuiz, validate_questions

QUESTION_COUNT = 5


def _build_prompt(week_name: str, material_text: str) -> str:
    return f"""You are an expert instructional designer for an introductory Computer Science Principles course.

Generate a weekly quiz with exactly {QUESTION_COUNT} questions based ONLY on the course material below.

Week: {week_name}

Requirements:
- Test conceptual understanding, not trivial memorization or trick questions.
- Use multiple_choice_question with exactly 4 answer options (one correct, answer_weight=100) OR true_false_question with exactly 2 options.
- Each question must be answerable from the provided material; do not invent facts.
- question_name: short label (e.g. "Q1: Binary representation").
- question_text: clear question stem (may include simple HTML like <p> tags).
- points_possible: 1 for each question.
- quiz_title: concise title like "{week_name} Quiz".

Course material:
{material_text}
"""


def generate_weekly_quiz(week_name: str, material_text: str) -> WeeklyQuiz:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Set GEMINI_API_KEY in .env (https://aistudio.google.com/apikey)"
        )

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=model,
        contents=_build_prompt(week_name, material_text),
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_json_schema=WeeklyQuiz.model_json_schema(),
        ),
    )

    text = response.text
    if not text:
        raise RuntimeError("Gemini returned empty response")

    quiz = WeeklyQuiz.model_validate_json(text)
    validate_questions(quiz)
    return quiz
