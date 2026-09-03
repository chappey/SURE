"""FastAPI dependency injection helpers."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request

from app.auth import require_lti_launch, require_oauth_configured
from app.canvas import get_canvas
from app.canvas_courses import course_is_teacher
from app.canvas_ids import normalize_canvas_course_id
from app.canvas_oauth import ensure_fresh_token

# quiz_id values are server-generated token_hex strings; enforce the shape at
# the router boundary so an id like "../x" can never reach filesystem paths.
QUIZ_ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
_QUIZ_ID_RE = re.compile(QUIZ_ID_PATTERN)


def validate_quiz_id(quiz_id: str) -> str:
    """Raise ``ValueError`` unless ``quiz_id`` is a safe identifier."""
    if not _QUIZ_ID_RE.match(quiz_id or ""):
        raise ValueError(f"Invalid quiz id: {quiz_id!r}")
    return quiz_id


def resolve_canvas_user_id(request: Request) -> str:
    """Return the Canvas user ID for the current session."""
    user_id = request.session.get("canvas_user_id")
    if user_id:
        return str(user_id)

    raise HTTPException(
        status_code=401,
        detail="User identity not found. Re-launch EasyLearn from Canvas.",
    )


def resolve_course_id(request: Request) -> int:
    """Extract and validate the numeric Canvas course ID from the LTI session."""
    raw = request.session.get("canvas_course_id")
    course_id = normalize_canvas_course_id(raw)
    if course_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "No active course ID found in session. "
                "Re-launch EasyLearn from Canvas with canvas_course_id configured."
            )
            if not raw
            else (
                f"Invalid course ID: {raw!r}. Configure the LTI custom field "
                "canvas_course_id=$Canvas.course.id"
            ),
        )
    return course_id


def resolve_canvas_client(request: Request):
    """Return a Canvas client using the session OAuth token."""
    require_oauth_configured()
    ensure_fresh_token(request)
    user_token = request.session.get("canvas_user_token")
    if not user_token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please authorize the app.",
        )
    return get_canvas(token=user_token)


_TEACHING_ROLES = frozenset(
    {"Teacher", "Instructor", "Teaching Assistant", "Administrator", "Admin", "ContentDeveloper"}
)


def require_teacher(request: Request) -> None:
    """Ensure the session belongs to a teaching role before quiz operations."""
    role = request.session.get("user_role")
    if role in _TEACHING_ROLES:
        return

    raise HTTPException(
        status_code=403,
        detail=(
            "EasyLearn is restricted to course instructors. "
            "Re-launch from Canvas with a teacher role."
        ),
    )


def validate_course_access(request: Request, course_id: int, canvas) -> None:
    """Ensure the user is a teacher in the target course."""
    if not course_is_teacher(canvas, course_id):
        raise HTTPException(
            status_code=403,
            detail="You do not have teacher access to that course.",
        )


CourseIdDep = Annotated[int, Depends(resolve_course_id)]
CanvasClientDep = Annotated[object, Depends(resolve_canvas_client)]
CanvasUserIdDep = Annotated[str, Depends(resolve_canvas_user_id)]
RequireTeacherDep = Annotated[None, Depends(require_teacher)]
RequireLtiLaunchDep = Annotated[None, Depends(require_lti_launch)]
# Validated path parameter: rejects traversal/separator characters before any
# storage access happens.
QuizIdPath = Annotated[
    str,
    Path(
        pattern=QUIZ_ID_PATTERN,
        max_length=128,
        description="Quiz draft identifier",
    ),
]
