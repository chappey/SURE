"""Request-scoped identity for LLM tracing (contextvars, not thread locals)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from starlette.requests import Request

_request_id: ContextVar[str] = ContextVar("ops_request_id", default="")
_user_id: ContextVar[str] = ContextVar("ops_user_id", default="")
_user_name: ContextVar[str] = ContextVar("ops_user_name", default="")
_course_id: ContextVar[str] = ContextVar("ops_course_id", default="")
_purpose: ContextVar[str] = ContextVar("ops_purpose", default="")


def bind_request(request: Request) -> None:
    """Copy session identity onto the current task so provider calls can log it."""
    session = getattr(request, "session", {}) or {}
    _request_id.set(str(getattr(request.state, "request_id", "") or ""))
    _user_id.set(str(session.get("canvas_user_id") or ""))
    _user_name.set(str(session.get("user_name") or ""))
    _course_id.set(str(session.get("canvas_course_id") or ""))


@contextmanager
def llm_purpose(purpose: str) -> Iterator[None]:
    token = _purpose.set(purpose)
    try:
        yield
    finally:
        _purpose.reset(token)


def snapshot() -> dict[str, str]:
    return {
        "request_id": _request_id.get(),
        "user_id": _user_id.get(),
        "user_name": _user_name.get(),
        "course_id": _course_id.get(),
        "purpose": _purpose.get(),
    }


def bind_snapshot(ident: dict[str, str]) -> None:
    """Re-attach a snapshot on a background thread (contextvars are task-local)."""
    _request_id.set(ident.get("request_id", ""))
    _user_id.set(ident.get("user_id", ""))
    _user_name.set(ident.get("user_name", ""))
    _course_id.set(ident.get("course_id", ""))
    _purpose.set(ident.get("purpose", ""))
