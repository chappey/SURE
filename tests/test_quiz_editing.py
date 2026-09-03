from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.quizzes_service import (
    delete_question_from_draft,
    update_question_in_draft,
)


@pytest.fixture
def sample_draft():
    return {
        "id": "test_quiz_123",
        "quiz_title": "Chemistry Quiz",
        "deployed": False,
        "published": False,
        "questions": [
            {
                "question_name": "Q1: Octet Rule",
                "question_text": "What is the octet rule?",
                "question_type": "multiple_choice_question",
                "points_possible": 1,
                "answers": [
                    {"answer_text": "8 electrons", "answer_weight": 100},
                    {"answer_text": "2 electrons", "answer_weight": 0},
                ],
            },
            {
                "question_name": "Q2: Valence Shell",
                "question_text": "What is the valence shell?",
                "question_type": "multiple_choice_question",
                "points_possible": 2,
                "answers": [
                    {"answer_text": "Outermost shell", "answer_weight": 100},
                    {"answer_text": "Innermost shell", "answer_weight": 0},
                ],
            },
            {
                "question_name": "Q3: Noble Gases",
                "question_text": "Are noble gases reactive?",
                "question_type": "true_false_question",
                "points_possible": 1,
                "answers": [
                    {"answer_text": "False", "answer_weight": 100},
                    {"answer_text": "True", "answer_weight": 0},
                ],
            },
        ],
    }


class TestDeleteQuestionFromDraft:
    def test_delete_middle_question_and_renumber(self, sample_draft):
        with patch("app.quizzes_service.get_quiz_draft", return_value=dict(sample_draft)), \
             patch("app.quizzes_service.update_quiz_draft", side_effect=lambda cid, qid, patch, created_by: {**sample_draft, **patch}):
            
            res = delete_question_from_draft(72, "test_quiz_123", question_index=1, user_name="uchaudhu@kent.edu")
            
            quiz = res["quiz"]
            assert len(quiz["questions"]) == 2
            assert res["deleted_question"]["question_name"] == "Q2: Valence Shell"
            # Q1 stays Q1
            assert quiz["questions"][0]["question_name"] == "Q1: Octet Rule"
            # Former Q3 is renumbered to Q2
            assert quiz["questions"][1]["question_name"] == "Q2: Noble Gases"

    def test_delete_first_question(self, sample_draft):
        with patch("app.quizzes_service.get_quiz_draft", return_value=dict(sample_draft)), \
             patch("app.quizzes_service.update_quiz_draft", side_effect=lambda cid, qid, patch, created_by: {**sample_draft, **patch}):
            
            res = delete_question_from_draft(72, "test_quiz_123", question_index=0)
            quiz = res["quiz"]
            assert len(quiz["questions"]) == 2
            assert quiz["questions"][0]["question_name"] == "Q1: Valence Shell"
            assert quiz["questions"][1]["question_name"] == "Q2: Noble Gases"

    def test_delete_last_question_of_list(self, sample_draft):
        with patch("app.quizzes_service.get_quiz_draft", return_value=dict(sample_draft)), \
             patch("app.quizzes_service.update_quiz_draft", side_effect=lambda cid, qid, patch, created_by: {**sample_draft, **patch}):
            
            res = delete_question_from_draft(72, "test_quiz_123", question_index=2)
            quiz = res["quiz"]
            assert len(quiz["questions"]) == 2
            assert quiz["questions"][0]["question_name"] == "Q1: Octet Rule"
            assert quiz["questions"][1]["question_name"] == "Q2: Valence Shell"

    def test_cannot_delete_sole_remaining_question(self):
        one_q_draft = {
            "id": "single_q",
            "questions": [{"question_name": "Q1: Only", "question_text": "Text"}],
        }
        with patch("app.quizzes_service.get_quiz_draft", return_value=one_q_draft):
            with pytest.raises(ValueError, match="A quiz must have at least one question"):
                delete_question_from_draft(72, "single_q", question_index=0)

    def test_out_of_bounds_index(self, sample_draft):
        with patch("app.quizzes_service.get_quiz_draft", return_value=sample_draft):
            with pytest.raises(IndexError, match="out of range"):
                delete_question_from_draft(72, "test_quiz_123", question_index=5)
            with pytest.raises(IndexError, match="out of range"):
                delete_question_from_draft(72, "test_quiz_123", question_index=-1)

    def test_nonexistent_quiz_raises_keyerror(self):
        with patch("app.quizzes_service.get_quiz_draft", return_value=None):
            with pytest.raises(KeyError, match="not found"):
                delete_question_from_draft(72, "missing_quiz", question_index=0)

    def test_deployed_draft_resets_deployment_state_when_zero_submissions(self, sample_draft):
        deployed_draft = dict(sample_draft)
        deployed_draft["deployed"] = True
        deployed_draft["published"] = False
        deployed_draft["canvas_quiz_id"] = 71
        deployed_draft["quiz_url"] = "http://canvas/quizzes/71"
        deployed_draft["agentic_feedback"] = {"enabled": True}

        course_mock = MagicMock()
        with patch("app.quizzes_service.get_quiz_draft", return_value=deployed_draft), \
             patch("app.canvas_courses.count_eligible_quiz_submissions", return_value=0), \
             patch("app.quizzes_service.update_quiz_draft", side_effect=lambda cid, qid, patch, created_by: {**deployed_draft, **patch}):
            
            res = delete_question_from_draft(72, "test_quiz_123", question_index=1, course=course_mock)
            quiz = res["quiz"]
            assert quiz["deployed"] is False
            assert quiz["published"] is False
            assert quiz["canvas_quiz_id"] is None
            assert quiz["quiz_url"] is None
            assert quiz["agentic_feedback"] is None

    def test_deployed_draft_blocks_deletion_if_submissions_exist(self, sample_draft):
        deployed_draft = dict(sample_draft)
        deployed_draft["deployed"] = True
        deployed_draft["canvas_quiz_id"] = 71

        course_mock = MagicMock()
        with patch("app.quizzes_service.get_quiz_draft", return_value=deployed_draft), \
             patch("app.canvas_courses.count_eligible_quiz_submissions", return_value=3):
            
            with pytest.raises(ValueError, match="Cannot delete questions from a quiz with existing student submissions"):
                delete_question_from_draft(72, "test_quiz_123", question_index=0, course=course_mock)


class TestUpdateQuestionInDraft:
    def test_update_question_content(self, sample_draft):
        updated_q = {
            "question_name": "Q1: Modified Octet Rule",
            "question_text": "Updated question prompt",
            "question_type": "multiple_choice_question",
            "points_possible": 5,
            "answers": [
                {"answer_text": "8 electrons", "answer_weight": 100},
            ],
        }
        with patch("app.quizzes_service.get_quiz_draft", return_value=dict(sample_draft)), \
             patch("app.quizzes_service.update_quiz_draft", side_effect=lambda cid, qid, patch, created_by: {**sample_draft, **patch}):
            
            res = update_question_in_draft(72, "test_quiz_123", question_index=0, question_data=updated_q)
            assert res["quiz"]["questions"][0]["question_name"] == "Q1: Modified Octet Rule"
            assert res["quiz"]["questions"][0]["points_possible"] == 5


class TestQuizEditingApiEndpoints:
    def test_delete_endpoint_success(self, sample_draft):
        from fastapi.testclient import TestClient
        from main import app
        from app.dependencies import require_lti_launch, require_teacher, resolve_course_id, resolve_canvas_client

        app.dependency_overrides[require_lti_launch] = lambda: None
        app.dependency_overrides[require_teacher] = lambda: None
        app.dependency_overrides[resolve_course_id] = lambda: 72
        fake_course = MagicMock()
        fake_canvas = MagicMock()
        fake_canvas.get_course.return_value = fake_course
        app.dependency_overrides[resolve_canvas_client] = lambda: fake_canvas

        try:
            with patch("app.routers.api.delete_question_from_draft") as mock_delete:
                mock_delete.return_value = {"quiz": sample_draft, "deleted_question": sample_draft["questions"][0]}
                with TestClient(app) as client:
                    resp = client.delete(
                        "/api/quizzes/test_quiz_123/questions/0",
                        headers={"origin": "https://easylearn.nathanchappie.com"},
                    )
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["status"] == "success"
                    assert "quiz" in data
                    mock_delete.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    def test_delete_endpoint_error_handling(self):
        from fastapi.testclient import TestClient
        from main import app
        from app.dependencies import require_lti_launch, require_teacher, resolve_course_id, resolve_canvas_client

        app.dependency_overrides[require_lti_launch] = lambda: None
        app.dependency_overrides[require_teacher] = lambda: None
        app.dependency_overrides[resolve_course_id] = lambda: 72
        fake_canvas = MagicMock()
        app.dependency_overrides[resolve_canvas_client] = lambda: fake_canvas

        try:
            with patch("app.routers.api.delete_question_from_draft", side_effect=ValueError("A quiz must have at least one question.")):
                with TestClient(app) as client:
                    resp = client.delete(
                        "/api/quizzes/test_quiz_123/questions/0",
                        headers={"origin": "https://easylearn.nathanchappie.com"},
                    )
                    assert resp.status_code == 400
                    assert "at least one question" in resp.json()["detail"]

            with patch("app.routers.api.delete_question_from_draft", side_effect=KeyError("Quiz draft not found")):
                with TestClient(app) as client:
                    resp = client.delete(
                        "/api/quizzes/nonexistent/questions/0",
                        headers={"origin": "https://easylearn.nathanchappie.com"},
                    )
                    assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_update_endpoint_success(self, sample_draft):
        from fastapi.testclient import TestClient
        from main import app
        from app.dependencies import require_lti_launch, require_teacher, resolve_course_id

        app.dependency_overrides[require_lti_launch] = lambda: None
        app.dependency_overrides[require_teacher] = lambda: None
        app.dependency_overrides[resolve_course_id] = lambda: 72

        try:
            with patch("app.routers.api.update_question_in_draft") as mock_update:
                mock_update.return_value = {"quiz": sample_draft, "updated_question": sample_draft["questions"][0]}
                with TestClient(app) as client:
                    payload = sample_draft["questions"][0]
                    resp = client.put(
                        "/api/quizzes/test_quiz_123/questions/0",
                        json=payload,
                        headers={"origin": "https://easylearn.nathanchappie.com"},
                    )
                    assert resp.status_code == 200
                    assert resp.json()["status"] == "success"
                    mock_update.assert_called_once()
        finally:
            app.dependency_overrides.clear()


class TestSaveFullQuizDraft:
    def test_save_full_draft_updates_title_and_questions(self, sample_draft):
        from app.quizzes_service import save_full_quiz_draft
        with patch("app.quizzes_service.get_quiz_draft", return_value=dict(sample_draft)), \
             patch("app.quizzes_service.update_quiz_draft", side_effect=lambda cid, qid, patch, created_by: {**sample_draft, **patch}):
            
            res = save_full_quiz_draft(
                course_id=72,
                quiz_id="test_quiz_123",
                quiz_title="Renamed Chemistry Quiz",
                questions=sample_draft["questions"][:2],
                user_name="uchaudhu@kent.edu",
            )
            quiz = res["quiz"]
            assert quiz["quiz_title"] == "Renamed Chemistry Quiz"
            assert len(quiz["questions"]) == 2

    def test_save_full_draft_empty_questions_raises_error(self, sample_draft):
        from app.quizzes_service import save_full_quiz_draft
        with patch("app.quizzes_service.get_quiz_draft", return_value=dict(sample_draft)):
            with pytest.raises(ValueError, match="must contain at least one question"):
                save_full_quiz_draft(72, "test_quiz_123", "Title", [])

    def test_save_full_draft_blocks_if_submissions_exist(self, sample_draft):
        from app.quizzes_service import save_full_quiz_draft
        deployed_draft = dict(sample_draft)
        deployed_draft["deployed"] = True
        deployed_draft["canvas_quiz_id"] = 71

        course_mock = MagicMock()
        with patch("app.quizzes_service.get_quiz_draft", return_value=deployed_draft), \
             patch("app.canvas_courses.count_eligible_quiz_submissions", return_value=5):
            with pytest.raises(ValueError, match="Cannot modify a quiz that already has active student submissions"):
                save_full_quiz_draft(72, "test_quiz_123", "Title", sample_draft["questions"], course=course_mock)


class TestDeleteEntireQuizDraft:
    def test_delete_entire_draft_success(self, sample_draft):
        from app.quizzes_service import delete_entire_quiz_draft
        with patch("app.quizzes_service.get_quiz_draft", return_value=dict(sample_draft)), \
             patch("app.quizzes_service.delete_quiz_draft", return_value=True):
            
            res = delete_entire_quiz_draft(72, "test_quiz_123")
            assert res["status"] == "success"

    def test_delete_entire_draft_blocks_if_submissions_exist(self, sample_draft):
        from app.quizzes_service import delete_entire_quiz_draft
        deployed_draft = dict(sample_draft)
        deployed_draft["deployed"] = True
        deployed_draft["canvas_quiz_id"] = 71

        course_mock = MagicMock()
        with patch("app.quizzes_service.get_quiz_draft", return_value=deployed_draft), \
             patch("app.canvas_courses.count_eligible_quiz_submissions", return_value=2):
            with pytest.raises(ValueError, match="Cannot delete a quiz that already has active student submissions"):
                delete_entire_quiz_draft(72, "test_quiz_123", course=course_mock)


class TestFullDraftApiEndpoints:
    def test_put_full_draft_endpoint(self, sample_draft):
        from fastapi.testclient import TestClient
        from main import app
        from app.dependencies import require_lti_launch, require_teacher, resolve_course_id, resolve_canvas_client

        app.dependency_overrides[require_lti_launch] = lambda: None
        app.dependency_overrides[require_teacher] = lambda: None
        app.dependency_overrides[resolve_course_id] = lambda: 72
        fake_canvas = MagicMock()
        fake_canvas.get_course.return_value = MagicMock()
        app.dependency_overrides[resolve_canvas_client] = lambda: fake_canvas

        try:
            with patch("app.routers.api.save_full_quiz_draft") as mock_save:
                mock_save.return_value = {"quiz": sample_draft}
                with TestClient(app) as client:
                    payload = {
                        "id": "test_quiz_123",
                        "quiz_title": "Chemistry Final",
                        "questions": sample_draft["questions"],
                    }
                    resp = client.put(
                        "/api/quizzes/test_quiz_123",
                        json=payload,
                        headers={"origin": "https://easylearn.nathanchappie.com"},
                    )
                    assert resp.status_code == 200
                    assert resp.json()["status"] == "success"
                    mock_save.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    def test_delete_full_draft_endpoint(self, sample_draft):
        from fastapi.testclient import TestClient
        from main import app
        from app.dependencies import require_lti_launch, require_teacher, resolve_course_id, resolve_canvas_client

        app.dependency_overrides[require_lti_launch] = lambda: None
        app.dependency_overrides[require_teacher] = lambda: None
        app.dependency_overrides[resolve_course_id] = lambda: 72
        fake_canvas = MagicMock()
        fake_canvas.get_course.return_value = MagicMock()
        app.dependency_overrides[resolve_canvas_client] = lambda: fake_canvas

        try:
            with patch("app.routers.api.delete_entire_quiz_draft") as mock_delete:
                mock_delete.return_value = {"status": "success", "quiz_id": "test_quiz_123"}
                with TestClient(app) as client:
                    resp = client.delete(
                        "/api/quizzes/test_quiz_123",
                        headers={"origin": "https://easylearn.nathanchappie.com"},
                    )
                    assert resp.status_code == 200
                    assert resp.json()["status"] == "success"
                    mock_delete.assert_called_once()
        finally:
            app.dependency_overrides.clear()
