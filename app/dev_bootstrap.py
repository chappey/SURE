"""Direct-access dev bootstrap (admin API token, no LTI/OAuth)."""

from __future__ import annotations

import logging

from starlette.requests import Request

from app import config
from app.auth import oauth_enabled
from app.canvas import get_canvas
from app.canvas_courses import list_teacher_courses
from app.canvas_ids import normalize_canvas_course_id

logger = logging.getLogger("easylearn")


def direct_dev_mode() -> bool:
    """True when using the shared admin token without OAuth."""
    return bool(config.CANVAS_API_TOKEN and not oauth_enabled())


def _pick_default_course_id() -> int | None:
    """Choose a course for direct dev when none is configured."""
    configured = normalize_canvas_course_id(config.CANVAS_COURSE_ID)
    if configured is not None:
        return configured

    try:
        canvas = get_canvas()
        courses = list_teacher_courses(canvas, include_course_id=configured)
        if courses:
            return int(courses[0]["id"])

        for course in canvas.get_courses(per_page=100):
            parsed = normalize_canvas_course_id(getattr(course, "id", None))
            if parsed is not None:
                return parsed
    except Exception as exc:
        logger.warning("Could not auto-select a Canvas course for direct dev: %s", exc)

    return None


def ensure_direct_dev_session(request: Request) -> None:
    """Seed session fields for http://canvas.docker:8000/ without an LTI launch."""
    if not direct_dev_mode() or request.session.get("lti_launched"):
        return

    session = request.session
    session.setdefault("user_name", "Dev User")
    session.setdefault("user_role", "Instructor")

    if normalize_canvas_course_id(session.get("canvas_course_id")) is not None:
        return

    course_id = _pick_default_course_id()
    if course_id is None:
        return

    session["canvas_course_id"] = str(course_id)
    if not session.get("course_name"):
        try:
            course = get_canvas().get_course(course_id)
            session["course_name"] = course.name
        except Exception:
            pass
