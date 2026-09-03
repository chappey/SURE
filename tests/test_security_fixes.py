"""Regression tests for security/logic fixes.

Covers: quiz-id path-traversal validation, deploy-path HTML sanitization,
confidence classification, exact-match LTI role parsing, and the TTL/bounded
LTI data storage.
"""

from __future__ import annotations

import time

import pytest

from app.agentic_feedback import CONFIDENCE_LABELS, confidence_is_high
from app.dependencies import validate_quiz_id
from app.lti import InMemoryDataStorage
from app.lti_claims import extract_lti_user_fields
from app.schemas import (
    DraftQuestion,
    DraftQuiz,
    GeneratedAnswer,
    sanitize_canvas_html,
    to_canvas_question,
)


ROLES_CLAIM = "https://purl.imsglobal.org/spec/lti/claim/roles"


# --- quiz_id validation -------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../../evil",
        "..",
        "a/b",
        "a\\b",
        "with space",
        ".hidden",
        "",
        "x" * 129,
    ],
)
def test_validate_quiz_id_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        validate_quiz_id(bad)


@pytest.mark.parametrize("good", ["ab12cd34", "Abc_-123", "0"])
def test_validate_quiz_id_accepts_safe(good):
    assert validate_quiz_id(good) == good


# --- HTML sanitization on the deploy path ------------------------------------


def test_sanitize_strips_script_blocks():
    dirty = "<p>Hello</p><script>alert(1)</script>"
    clean = sanitize_canvas_html(dirty)
    assert "<script" not in clean.lower()
    assert "<p>Hello</p>" in clean


def test_sanitize_strips_event_handlers_and_dangerous_urls():
    dirty = '<img src="x" onerror="steal()"><a href="javascript:alert(1)">c</a>'
    clean = sanitize_canvas_html(dirty)
    assert "onerror" not in clean
    assert "javascript:" not in clean


def test_to_canvas_question_sanitizes_student_facing_fields():
    q = DraftQuestion(
        question_name="Q1 <script>x</script>",
        question_text="What is 2+2? <script>alert(1)</script>",
        question_type="multiple_choice_question",
        answers=[
            GeneratedAnswer(answer_text="4", answer_weight=100, answer_comments="<i>ok</i>"),
            GeneratedAnswer(answer_text="5", answer_weight=0, answer_comments=""),
        ],
    )
    payload = to_canvas_question(q)
    assert "<script" not in payload["question_text"]
    assert payload["answers"][0]["answer_comments"] == "<i>ok</i>"  # benign tags kept


# --- confidence classification -------------------------------------------------


def test_confidence_is_high_matches_actual_labels():
    # The top two meta-question options are high confidence.
    assert confidence_is_high(CONFIDENCE_LABELS[3])
    assert confidence_is_high(CONFIDENCE_LABELS[4])
    # Everything else is not.
    for label in CONFIDENCE_LABELS[:3]:
        assert not confidence_is_high(label)
    assert not confidence_is_high(None)
    assert not confidence_is_high("")


def test_confidence_is_high_tolerates_legacy_short_forms():
    assert confidence_is_high("High")
    assert confidence_is_high(" 5 ")
    assert not confidence_is_high("moderate")


# --- LTI role parsing ----------------------------------------------------------


def _launch(roles):
    return {
        "https://purl.imsglobal.org/spec/lti/claim/custom": {},
        ROLES_CLAIM: roles,
    }


def test_roles_full_urn_instructor_maps_to_teacher():
    assert (
        extract_lti_user_fields(_launch(["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"]))[
            "user_role"
        ]
        == "Teacher"
    )


def test_roles_short_form_ta_maps_to_teaching_assistant():
    assert extract_lti_user_fields(_launch(["TeachingAssistant"]))["user_role"] == "Teaching Assistant"


def test_roles_learner_maps_to_student():
    assert (
        extract_lti_user_fields(_launch(["urn:lti:role:ims/lis/Learner"]))["user_role"]
        == "Student"
    )


def test_roles_substring_collisions_do_not_escalate():
    # "LibraryAssistant" must NOT match the old "Assistant" substring rule.
    assert (
        extract_lti_user_fields(_launch(["http://purl.imsglobal.org/vocab/lis/v2/system/person#LibraryAssistant"]))[
            "user_role"
        ]
        is None
    )
    # Plain institutional "Staff" is not a teaching role.
    assert (
        extract_lti_user_fields(_launch(["http://purl.imsglobal.org/vocab/lis/v2/institution/person#Staff"]))[
            "user_role"
        ]
        is None
    )


# --- TTL / bounded LTI data storage --------------------------------------------


def test_storage_expires_entries():
    store = InMemoryDataStorage(default_expiration=5)
    store.set_value("nonce", {"v": 1}, exp=0.05)
    assert store.check_value("nonce")
    time.sleep(0.08)
    assert not store.check_value("nonce")
    assert store.get_value("nonce") is None


def test_storage_default_expiration_used_when_none():
    store = InMemoryDataStorage(default_expiration=60)
    store.set_value("k", "v")
    assert store.get_value("k") == "v"
    assert store.can_set_keys_expiration()


def test_storage_is_bounded():
    store = InMemoryDataStorage(max_entries=4)
    for i in range(10):
        store.set_value(f"k{i}", i, exp=3600)
    assert len(store._cache) <= 4
    # Most recent entries survive eviction.
    assert store.get_value("k9") == 9
