"""FastAPI dependency injection helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app import config
from app.canvas import get_canvas
from app.canvas_courses import course_is_teacher, list_teacher_courses


def resolve_canvas_user_id(request: Request) -> str:
    """Return the Canvas user ID for the current session."""
    user_id = request.session.get("canvas_user_id")
    if user_id:
        return str(user_id)

    # Dev fallback when using a shared API token without OAuth/LTI user context
    if config.CANVAS_API_TOKEN and not (config.CANVAS_CLIENT_ID and config.CANVAS_CLIENT_SECRET):
        return "dev-local"

    raise HTTPException(
        status_code=401,
        detail="User identity not found. Re-launch EasyLearn from Canvas.",
    )


def resolve_course_id(request: Request) -> int:
    """Extract and validate the numeric Canvas course ID from session or config."""
    course_id = request.session.get("canvas_course_id") or config.CANVAS_COURSE_ID
    if not course_id:
        raise HTTPException(
            status_code=400,
            detail="No active course ID found in session or config.",
        )
    try:
        return int(course_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid course ID: {course_id!r}. The Canvas API requires a numeric database ID. "
                "Please configure your Canvas LTI Developer Key with the Custom Field: "
                "canvas_course_id=$Canvas.course.id"
            ),
        )


def resolve_canvas_client(request: Request):
    """Return a Canvas client using the session token or configured fallback token."""
    user_token = request.session.get("canvas_user_token")
    if config.CANVAS_CLIENT_ID and config.CANVAS_CLIENT_SECRET and not user_token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please authorize the app.",
        )
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
