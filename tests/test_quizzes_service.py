from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import ANY, patch

from app.quizzes_service import (
    _ensure_quiz_url,
    _fetch_canvas_quiz_meta,
    _quiz_status,
    _read_ttl_cache,
    build_quizzes_overview,
    get_cached_stats,
    get_quiz_stats,
    process_agentic_feedback,
    save_stats_cache,
)


class TestQuizStatus:
    def test_published(self):
        assert _quiz_status(deployed=True, published=True) == "published"

    def test_deployed_not_published(self):
        assert _quiz_status(deployed=True, published=False) == "deployed"

    def test_draft(self):
        assert _quiz_status(deployed=False, published=False) == "draft"

    def test_draft_even_if_published_flag_without_deploy(self):
        assert _quiz_status(deployed=False, published=True) == "published"


class TestReadTtlCache:
    def test_missing_file_returns_none(self, tmp_path: Path):
        path = tmp_path / "nonexistent.json"
        assert _read_ttl_cache(path, ttl_seconds=60) is None

    def test_expired_file_returns_none(self, tmp_path: Path):
        path = tmp_path / "old.json"
        path.write_text('{"key": "value"}')
        time.sleep(0.01)
        assert _read_ttl_cache(path, ttl_seconds=0.001) is None

    def test_valid_file_returns_data(self, tmp_path: Path):
        path = tmp_path / "fresh.json"
        path.write_text('{"key": "value"}')
        result = _read_ttl_cache(path, ttl_seconds=60)
        assert result == {"key": "value"}

    def test_corrupted_file_returns_none(self, tmp_path: Path):
        path = tmp_path / "corrupt.json"
        path.write_text("not json")
        assert _read_ttl_cache(path, ttl_seconds=60) is None


class TestGetCachedStats:
    def test_returns_none_when_no_cache(self, tmp_path: Path):
        assert get_cached_stats(1, 42) is None

    def test_returns_cached_data(self, tmp_path: Path):
        save_stats_cache(1, 42, {"available": True, "submission_count": 5})
        result = get_cached_stats(1, 42)
        assert result is not None
        assert result["available"] is True
        assert result["submission_count"] == 5


class TestFetchCanvasQuizMeta:
    def test_caches_meta(self, tmp_path: Path):
        class FakeQuiz:
            published = True
            question_count = 10

        class FakeCourse:
            def get_quiz(self, quiz_id):
                return FakeQuiz()

        course = FakeCourse()
        meta = _fetch_canvas_quiz_meta(course, 1, 42)
        assert meta == {"published": True, "question_count": 10}

    def test_uses_cache_on_second_call(self, tmp_path: Path):
        call_count = 0

        class FakeQuiz:
            published = True
            question_count = 10

        class FakeCourse:
            def get_quiz(self, quiz_id):
                nonlocal call_count
                call_count += 1
                return FakeQuiz()

        course = FakeCourse()
        _fetch_canvas_quiz_meta(course, 1, 42)
        _fetch_canvas_quiz_meta(course, 1, 42)
        assert call_count == 1


class TestGetQuizStats:
    def test_uses_cache_first(self, tmp_path: Path):
        save_stats_cache(1, 42, {"available": True, "submission_count": 5})
        result = get_quiz_stats(None, None, 1, 42)
        assert result["submission_count"] == 5


class TestEnsureQuizUrl:
    def test_adds_url_when_canvas_quiz_id_present(self, monkeypatch):
        monkeypatch.setattr("app.config.canvas_quiz_url", lambda c, q: f"https://canvas.test/courses/{c}/quizzes/{q}")
        result = _ensure_quiz_url({"canvas_quiz_id": 99}, 1)
        assert result["quiz_url"] == "https://canvas.test/courses/1/quizzes/99"

    def test_no_url_when_no_canvas_quiz_id(self):
        result = _ensure_quiz_url({"id": "abc"}, 1)
        assert "quiz_url" not in result


class TestBuildQuizzesOverview:
    def test_returns_empty_when_no_quizzes(self, tmp_path: Path):
        overview = build_quizzes_overview(course=None, canvas=None, course_id=999)
        assert overview == []


class TestProcessAgenticFeedback:
    def test_raises_when_agentic_feedback_disabled(self, sample_draft):
        draft = dict(sample_draft, includes_agentic_feedback=False)
        import pytest
        with pytest.raises(ValueError, match="not have agentic feedback"):
            process_agentic_feedback(course=None, course_id=1, draft=draft)

    def test_raises_when_no_mapping(self):
        draft = {
            "includes_agentic_feedback": True,
            "agentic_feedback": {"questions": []},
            "canvas_quiz_id": "42",
        }
        import pytest
        with pytest.raises(ValueError, match="No agentic question mapping"):
            process_agentic_feedback(course=None, course_id=1, draft=draft)

    def test_raises_when_not_deployed(self):
        draft = {
            "includes_agentic_feedback": True,
            "agentic_feedback": {"questions": [{"content_index": 0}]},
            "canvas_quiz_id": None,
        }
        import pytest
        with pytest.raises(ValueError, match="not been deployed"):
            process_agentic_feedback(course=None, course_id=1, draft=draft)

    @patch("app.quizzes_service.fetch_quiz_submissions_with_answers")
    @patch("app.quizzes_service.generate_batched_feedback")
    @patch("app.quizzes_service.update_quiz_submission_comments")
    @patch("app.quizzes_service.update_quiz_draft")
    def test_processes_submissions(
        self,
        mock_update_draft,
        mock_update_comments,
        mock_generate,
        mock_fetch_subs,
        sample_draft,
        sample_submissions,
        sample_batch_feedback_items,
    ):
        mock_fetch_subs.return_value = sample_submissions
        mock_generate.return_value = sample_batch_feedback_items

        result = process_agentic_feedback(
            course="fake-course",
            course_id=1,
            draft=sample_draft,
        )

        assert result["eligible"] == 2
        assert result["processed"] == 2
        assert result["skipped"] == 0
        assert mock_generate.called
        assert mock_update_comments.call_count == 2
        assert mock_update_draft.called

    @patch("app.quizzes_service.fetch_quiz_submissions_with_answers")
    @patch("app.quizzes_service.generate_batched_feedback")
    @patch("app.quizzes_service.update_quiz_submission_comments")
    @patch("app.quizzes_service.update_quiz_draft")
    def test_skips_already_processed(
        self,
        mock_update_draft,
        mock_update_comments,
        mock_generate,
        mock_fetch_subs,
        sample_draft,
        sample_submissions,
        sample_batch_feedback_items,
    ):
        mock_fetch_subs.return_value = sample_submissions
        mock_generate.return_value = sample_batch_feedback_items
        draft = dict(sample_draft)
        draft["agentic_feedback_processed"] = {"1": {"processed_at": time.time(), "questions": 4, "user_id": 10}}

        result = process_agentic_feedback(
            course="fake-course",
            course_id=1,
            draft=draft,
        )

        assert result["eligible"] == 2
        assert result["skipped"] == 1
        assert result["processed"] == 1

    @patch("app.quizzes_service.fetch_quiz_submissions_with_answers")
    @patch("app.quizzes_service.generate_batched_feedback")
    @patch("app.quizzes_service.update_quiz_submission_comments")
    @patch("app.quizzes_service.update_quiz_draft")
    def test_force_reprocesses_all(
        self,
        mock_update_draft,
        mock_update_comments,
        mock_generate,
        mock_fetch_subs,
        sample_draft,
        sample_submissions,
        sample_batch_feedback_items,
    ):
        mock_fetch_subs.return_value = sample_submissions
        mock_generate.return_value = sample_batch_feedback_items
        draft = dict(sample_draft)
        draft["agentic_feedback_processed"] = {"1": {"processed_at": time.time(), "questions": 4, "user_id": 10}}

        result = process_agentic_feedback(
            course="fake-course",
            course_id=1,
            draft=draft,
            force=True,
        )

        assert result["eligible"] == 2
        assert result["skipped"] == 0
        assert result["processed"] == 2

    @patch("app.quizzes_service.fetch_quiz_submissions_with_answers")
    def test_max_submissions_cap(
        self,
        mock_fetch_subs,
        sample_draft,
        sample_submissions,
    ):
        mock_fetch_subs.return_value = sample_submissions

        with patch("app.quizzes_service.generate_batched_feedback", return_value=[]) as mock_gen:
            with patch("app.quizzes_service.update_quiz_draft"):
                result = process_agentic_feedback(
                    course="fake-course",
                    course_id=1,
                    draft=sample_draft,
                    max_submissions=1,
                )
                assert result["processed"] == 0
                assert result["eligible"] == 2

    @patch("app.quizzes_service.fetch_quiz_submissions_with_answers")
    @patch("app.quizzes_service.generate_batched_feedback")
    def test_errors_collected(
        self,
        mock_generate,
        mock_fetch_subs,
        sample_draft,
        sample_submissions,
    ):
        mock_fetch_subs.return_value = sample_submissions
        mock_generate.return_value = []
        with patch("app.quizzes_service.update_quiz_draft"):
            result = process_agentic_feedback(
                course="fake-course",
                course_id=1,
                draft=sample_draft,
            )
            assert len(result["errors"]) == 2
            assert result["errors"][0]["error"] == "No feedback generated"
