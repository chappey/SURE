from __future__ import annotations

import json
from unittest.mock import ANY, MagicMock, patch

import pytest

from app.generation import _build_prompt, generate_weekly_quiz
from app.schemas import DraftQuiz


class TestBuildPrompt:
    def test_contains_week_name(self):
        prompt = _build_prompt(
            week_name="Week 3: Sorting",
            material_text="Bubble sort is O(n^2).",
            num_mc=2,
            num_tf=1,
            num_matching=0,
            mc_options=4,
            matching_pairs=4,
            include_answer_feedback=False,
        )
        assert "Week 3: Sorting" in prompt

    def test_contains_material(self):
        prompt = _build_prompt(
            week_name="Test",
            material_text="Quick sort is O(n log n) average.",
            num_mc=1,
            num_tf=0,
            num_matching=0,
            mc_options=4,
            matching_pairs=4,
            include_answer_feedback=False,
        )
        assert "Quick sort is O(n log n) average." in prompt

    def test_contains_requirements(self):
        prompt = _build_prompt(
            week_name="Test",
            material_text="Content.",
            num_mc=3,
            num_tf=2,
            num_matching=1,
            mc_options=5,
            matching_pairs=4,
            include_answer_feedback=False,
        )
        assert "exactly 6 questions" in prompt
        assert "multiple_choice_question" in prompt
        assert "true_false_question" in prompt
        assert "matching_question" in prompt

    def test_include_answer_feedback(self):
        prompt = _build_prompt(
            week_name="Test",
            material_text="Content.",
            num_mc=1,
            num_tf=0,
            num_matching=0,
            mc_options=4,
            matching_pairs=4,
            include_answer_feedback=True,
        )
        assert "correct_comments" in prompt
        assert "incorrect_comments" in prompt

    def test_contains_difficulty_distribution(self):
        prompt = _build_prompt(
            week_name="Test",
            material_text="Content.",
            num_mc=2,
            num_tf=1,
            num_matching=0,
            mc_options=4,
            matching_pairs=4,
            include_answer_feedback=False,
            difficulty_counts={"easy": 1, "medium": 1, "hard": 1},
        )
        assert "1 'easy' questions, 1 'medium' questions, and 1 'hard' questions" in prompt
        assert "difficulty" in prompt

    def test_no_answer_feedback(self):
        prompt = _build_prompt(
            week_name="Test",
            material_text="Content.",
            num_mc=1,
            num_tf=0,
            num_matching=0,
            mc_options=4,
            matching_pairs=4,
            include_answer_feedback=False,
        )
        assert "leave both as empty strings" in prompt

    def test_custom_instructions_included(self):
        prompt = _build_prompt(
            week_name="Test",
            material_text="Content.",
            num_mc=1,
            num_tf=0,
            num_matching=0,
            mc_options=4,
            matching_pairs=4,
            include_answer_feedback=False,
            custom_instructions="Focus on Big-O notation.",
        )
        assert "Focus on Big-O notation." in prompt

    def test_custom_instructions_omitted_when_empty(self):
        prompt = _build_prompt(
            week_name="Test",
            material_text="Content.",
            num_mc=1,
            num_tf=0,
            num_matching=0,
            mc_options=4,
            matching_pairs=4,
            include_answer_feedback=False,
            custom_instructions="",
        )
        assert "Instructor specific" not in prompt

    def test_mc_options_minimum(self):
        prompt = _build_prompt(
            week_name="Test",
            material_text="Content.",
            num_mc=1,
            num_tf=0,
            num_matching=0,
            mc_options=2,
            matching_pairs=4,
            include_answer_feedback=False,
        )
        assert "2 answer options" in prompt

    def test_grounding_rules_present(self):
        prompt = _build_prompt(
            week_name="Test",
            material_text="Content.",
            num_mc=1,
            num_tf=0,
            num_matching=0,
            mc_options=4,
            matching_pairs=4,
            include_answer_feedback=False,
        )
        assert "Grounding rules" in prompt
        assert "Do NOT invent" in prompt


class TestGenerateWeeklyQuiz:
    def test_returns_draft_quiz(self):
        valid_json = json.dumps({
            "quiz_title": "Week 1 Quiz",
            "questions": [
                {
                    "question_name": "Q1",
                    "question_text": "<p>What is 2+2?</p>",
                    "question_type": "multiple_choice_question",
                    "points_possible": 1,
                    "answers": [
                        {"answer_text": "4", "answer_weight": 100},
                        {"answer_text": "3", "answer_weight": 0},
                    ],
                }
            ],
        })

        def fake_generate_json(model, prompt, schema):
            return valid_json

        with patch("app.generation.provider_generate_json", side_effect=fake_generate_json):
            with patch("app.generation.resolve_model") as mock_resolve:
                mock_entry = MagicMock(id="test-model", provider="openrouter", model="test-model")
                mock_resolve.return_value = mock_entry
                quiz, entry = generate_weekly_quiz(
                    week_name="Week 1",
                    material_text="2+2=4",
                    num_mc=1,
                    num_tf=0,
                    num_matching=0,
                    model_id="test-model",
                )
                assert isinstance(quiz, DraftQuiz)
                assert quiz.quiz_title == "Week 1 Quiz"
                assert len(quiz.questions) == 1
                assert entry.id == "test-model"

    def test_feedback_enabled_not_overwritten(self):
        valid_json = json.dumps({
            "quiz_title": "Test Quiz",
            "questions": [
                {
                    "question_name": "Q1",
                    "question_text": "<p>Test?</p>",
                    "question_type": "multiple_choice_question",
                    "points_possible": 1,
                    "answers": [
                        {"answer_text": "A", "answer_weight": 100},
                        {"answer_text": "B", "answer_weight": 0},
                    ],
                }
            ],
        })

        with patch("app.generation.provider_generate_json", return_value=valid_json):
            with patch("app.generation.resolve_model") as mock_resolve:
                mock_entry = MagicMock(id="test", provider="openrouter", model="test")
                mock_resolve.return_value = mock_entry
                quiz, _ = generate_weekly_quiz(
                    week_name="Test",
                    material_text="Content.",
                    num_mc=1,
                    model_id="test",
                )
                assert quiz.questions[0].feedback_enabled is True

    def test_raises_on_invalid_quiz(self):
        invalid_json = json.dumps({
            "quiz_title": "Bad Quiz",
            "questions": [
                {
                    "question_name": "Q1",
                    "question_text": "<p>Test?</p>",
                    "question_type": "true_false_question",
                    "answers": [
                        {"answer_text": "Only one option", "answer_weight": 100},
                    ],
                }
            ],
        })

        with patch("app.generation.provider_generate_json", return_value=invalid_json):
            with patch("app.generation.resolve_model") as mock_resolve:
                mock_entry = MagicMock(id="test", provider="openrouter", model="test")
                mock_resolve.return_value = mock_entry
                with pytest.raises(ValueError, match="exactly 2 answers"):
                    generate_weekly_quiz(
                        week_name="Test",
                        material_text="Content.",
                        num_mc=0,
                        num_tf=1,
                        model_id="test",
                    )
