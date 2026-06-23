"""FastAPI dependency injection helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app import config
from app.auth import oauth_enabled
from app.canvas import get_canvas
from app.canvas_courses import course_is_teacher, list_teacher_courses
from app.canvas_ids import normalize_canvas_course_id


def resolve_canvas_user_id(request: Request) -> str:
    """Return the Canvas user ID for the current session."""
    user_id = request.session.get("canvas_user_id")
    if user_id:
        return str(user_id)

    # Dev fallback when using a shared API token without OAuth/LTI user context
    if config.CANVAS_API_TOKEN and not oauth_enabled():
        return "dev-local"

    raise HTTPException(
        status_code=401,
        detail="User identity not found. Re-launch EasyLearn from Canvas.",
    )


def resolve_course_id(request: Request) -> int:
    """Extract and validate the numeric Canvas course ID from session or config."""
    raw = request.session.get("canvas_course_id") or config.CANVAS_COURSE_ID
    course_id = normalize_canvas_course_id(raw)
    if course_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "No active course ID found in session or config. "
                "Re-launch EasyLearn from Canvas, or set CANVAS_COURSE_ID in .env."
            )
            if not raw
            else (
                f"Invalid course ID: {raw!r}. Configure the LTI custom field "
                "canvas_course_id=$Canvas.course.id"
            ),
        )
    return course_id


def resolve_canvas_client(request: Request):
    """Return a Canvas client using the session token or configured fallback token."""
    user_token = request.session.get("canvas_user_token")
    if oauth_enabled():
        if not user_token:
            raise HTTPException(
                status_code=401,
                detail="Authentication required. Please authorize the app.",
            )
        return get_canvas(token=user_token)
    return get_canvas(token=user_token)


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
