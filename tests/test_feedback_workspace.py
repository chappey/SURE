from __future__ import annotations

from app.feedback_workspace import filter_content_question_stats, is_meta_question_stat


class TestFilterContentQuestionStats:
    def test_excludes_feedback_banner_rows(self):
        questions = [
            {"id": "583", "question_text": "<p>Which operator?</p>", "responses": 1, "correct_count": 1},
            {
                "id": "584",
                "question_text": '<p style="color:#b00020;">Question 1 Feedback (Not Graded)</p>',
                "responses": 0,
                "correct_count": 0,
            },
            {
                "id": "585",
                "question_text": '<p>Question 1 Feedback (Not Graded)</p>',
                "responses": 0,
                "correct_count": 0,
            },
        ]
        draft = {
            "agentic_feedback": {
                "questions": [{"content_index": 0, "content_canvas_id": "583"}]
            }
        }
        filtered = filter_content_question_stats(questions, draft)
        assert len(filtered) == 1
        assert filtered[0]["id"] == "583"

    def test_meta_heuristic_without_mapping(self):
        assert is_meta_question_stat(
            {"question_name": "", "question_text": "Question 2 Feedback (Not Graded)"}
        )
        assert not is_meta_question_stat(
            {"question_name": "", "question_text": "<p>What is an ADT?</p>"}
        )
