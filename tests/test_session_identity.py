"""Unit tests for LTI launch session identity binding."""

from __future__ import annotations

from types import SimpleNamespace

from app.session_identity import apply_lti_launch_to_session

_ROLE_INSTRUCTOR = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"


def _launch(
    *,
    sub: str,
    name: str,
    course_id: int = 70,
    title: str = "Test Course",
    canvas_user_id: str | None = "uid-b",
) -> dict:
    custom = {"canvas_course_id": str(course_id)}
    if canvas_user_id is not None:
        custom["canvas_user_id"] = canvas_user_id
    return {
        "sub": sub,
        "name": name,
        "email": f"{name.lower().replace(' ', '.')}@example.com",
        "https://purl.imsglobal.org/spec/lti/claim/roles": [_ROLE_INSTRUCTOR],
        "https://purl.imsglobal.org/spec/lti/claim/custom": custom,
        "https://purl.imsglobal.org/spec/lti/claim/context": {
            "id": str(course_id),
            "title": title,
        },
    }


def _request_with_session(data: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(session=dict(data or {}))


class TestApplyLtiLaunchToSession:
    def test_user_switch_clears_oauth_and_identity(self):
        request = _request_with_session(
            {
                "lti_launched": True,
                "lti_sub": "sub-a",
                "user_name": "User A",
                "user_email": "a@example.com",
                "user_role": "Teacher",
                "canvas_user_id": "uid-a",
                "canvas_course_id": "11",
                "course_name": "Old Course",
                "canvas_user_token": "user-a-access-token",
                "canvas_refresh_token": "user-a-refresh-token",
                "canvas_token_expires_at": 9999999999.0,
                "oauth_state": "stale-state",
            }
        )

        apply_lti_launch_to_session(
            request,
            _launch(sub="sub-b", name="User B", course_id=70, title="Test Course", canvas_user_id="uid-b"),
        )

        assert request.session["lti_launched"] is True
        assert request.session["lti_sub"] == "sub-b"
        assert request.session["user_name"] == "User B"
        assert request.session["canvas_course_id"] == "70"
        assert request.session["canvas_user_id"] == "uid-b"
        assert request.session["course_name"] == "Test Course"
        assert "canvas_user_token" not in request.session
        assert "canvas_refresh_token" not in request.session
        assert "canvas_token_expires_at" not in request.session
        assert "oauth_state" not in request.session
        assert request.session.get("user_name") != "User A"

    def test_same_user_relaunch_keeps_oauth_token(self):
        request = _request_with_session(
            {
                "lti_launched": True,
                "lti_sub": "sub-b",
                "user_name": "User B",
                "canvas_user_id": "uid-b",
                "canvas_course_id": "70",
                "canvas_user_token": "user-b-access-token",
                "canvas_refresh_token": "user-b-refresh-token",
            }
        )

        apply_lti_launch_to_session(
            request,
            _launch(sub="sub-b", name="User B", course_id=70, title="Test Course", canvas_user_id="uid-b"),
        )

        assert request.session["canvas_user_token"] == "user-b-access-token"
        assert request.session["canvas_refresh_token"] == "user-b-refresh-token"
        assert request.session["canvas_user_id"] == "uid-b"
        assert request.session["user_name"] == "User B"
        assert request.session["lti_sub"] == "sub-b"

    def test_user_switch_with_anonymous_lti_clears_stale_name(self):
        request = _request_with_session(
            {
                "lti_sub": "sub-a",
                "user_name": "User A",
                "canvas_user_token": "user-a-token",
            }
        )
        launch = _launch(sub="sub-b", name="User B", canvas_user_id=None)
        del launch["name"]

        apply_lti_launch_to_session(request, launch)

        assert "user_name" not in request.session
        assert "canvas_user_token" not in request.session
        assert request.session["lti_sub"] == "sub-b"

    def test_same_user_anonymous_relaunch_keeps_oauth_profile_name(self):
        request = _request_with_session(
            {
                "lti_sub": "sub-b",
                "user_name": "User B",
                "user_email": "b@example.com",
                "canvas_user_id": "uid-b",
                "canvas_user_token": "user-b-token",
            }
        )
        launch = _launch(sub="sub-b", name="ignored", canvas_user_id=None)
        del launch["name"]
        del launch["email"]

        apply_lti_launch_to_session(request, launch)

        assert request.session["user_name"] == "User B"
        assert request.session["user_email"] == "b@example.com"
        assert request.session["canvas_user_token"] == "user-b-token"

    def test_canvas_user_id_mismatch_clears_stale_token_despite_same_sub(self):
        """Same lti_sub but different canvas_user_id: stale OAuth token cleared.

        Catches the bug where a previous user's refresh token survived into
        the next user's session because sub happened to match but the Canvas
        user id differed.
        """
        request = _request_with_session(
            {
                "lti_sub": "sub-b",
                "canvas_user_id": "uid-a",  # stale: belongs to User A
                "canvas_user_token": "user-a-stale-token",
                "canvas_refresh_token": "user-a-stale-refresh",
                "user_name": "User A",
            }
        )

        apply_lti_launch_to_session(
            request,
            _launch(sub="sub-b", name="User B", canvas_user_id="uid-b"),
        )

        assert request.session["canvas_user_id"] == "uid-b"
        assert request.session["lti_sub"] == "sub-b"
        assert "canvas_user_token" not in request.session
        assert "canvas_refresh_token" not in request.session
        assert request.session["user_name"] == "User B"

    def test_anonymous_relaunch_does_not_wipe_on_missing_session_canvas_user_id(self):
        """No stored canvas_user_id + anonymous launch: sub match preserves tokens."""
        request = _request_with_session(
            {
                "lti_sub": "sub-b",
                "canvas_user_token": "user-b-token",
            }
        )
        launch = _launch(sub="sub-b", name="User B", canvas_user_id=None)
        del launch["name"]

        apply_lti_launch_to_session(request, launch)

        assert request.session["canvas_user_token"] == "user-b-token"
        assert request.session["lti_sub"] == "sub-b"
