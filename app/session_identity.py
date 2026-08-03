"""LTI launch → session identity binding (clear stale OAuth on user switch)."""

from __future__ import annotations

import logging

from starlette.requests import Request

from app.canvas_ids import extract_course_id_from_lti_launch
from app.canvas_oauth import clear_tokens
from app.lti_claims import extract_lti_user_fields

logger = logging.getLogger("easylearn")

_IDENTITY_KEYS = (
    "user_name",
    "user_email",
    "user_role",
    "lti_sub",
    "canvas_user_id",
    "canvas_course_id",
    "course_name",
    "oauth_state",
)


def apply_lti_launch_to_session(request: Request, launch_data: dict) -> None:
    """Bind validated LTI launch claims onto the browser session.

    Reset OAuth tokens and identity keys when the LTI subject OR the Canvas
    user id changes — so a previous professor's stale OAuth token cannot leak
    into the next Canvas user's EasyLearn session. Anonymous launches (no
    canvas_user_id claim) fall back to sub-only comparison.
    """
    user_fields = extract_lti_user_fields(launch_data)
    new_sub = user_fields.get("lti_sub")
    new_canvas_user_id = user_fields.get("canvas_user_id")
    old_sub = request.session.get("lti_sub")
    old_canvas_user_id = request.session.get("canvas_user_id")

    # Reset when the LTI subject changes OR the Canvas user id changes. The
    # latter catches a stale OAuth token bound to a different Canvas user
    # (e.g. a previous professor's refresh token surviving into the next
    # instructor's session). Anonymous launches omit canvas_user_id; fall back
    # to sub-only comparison so privacy mode does not spuriously wipe state.
    identity_changed = old_sub != new_sub or (
        new_canvas_user_id is not None
        and old_canvas_user_id is not None
        and old_canvas_user_id != new_canvas_user_id
    )
    if identity_changed:
        clear_tokens(request)
        for key in _IDENTITY_KEYS:
            request.session.pop(key, None)
        logger.info(
            "LTI identity reset: previous_sub=%r new_sub=%r "
            "previous_canvas_user_id=%r new_canvas_user_id=%r",
            old_sub,
            new_sub,
            old_canvas_user_id,
            new_canvas_user_id,
        )

    request.session["lti_launched"] = True

    # Overwrite only when the launch carries a value. Anonymous LTI privacy
    # omits name/email — do not wipe a profile filled in by OAuth.
    for key in ("user_name", "user_email", "user_role"):
        val = user_fields.get(key)
        if val:
            request.session[key] = val

    new_sub_val = user_fields.get("lti_sub")
    if new_sub_val:
        request.session["lti_sub"] = new_sub_val

    canvas_user_id_val = user_fields.get("canvas_user_id")
    if canvas_user_id_val:
        request.session["canvas_user_id"] = canvas_user_id_val

    course_id = extract_course_id_from_lti_launch(launch_data)
    if course_id is not None:
        request.session["canvas_course_id"] = str(course_id)
        logger.info(
            "LTI launch: user=%r course_id=%s sub=%r",
            request.session.get("user_name"),
            course_id,
            request.session.get("lti_sub"),
        )
    else:
        logger.warning("LTI launch: no course id in launch claims")
        request.session.pop("canvas_course_id", None)

    context = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/context", {}) or {}
    title = context.get("title")
    if title:
        request.session["course_name"] = title
    else:
        request.session.pop("course_name", None)
