"""Per-request LLM HTTP timeout override (used by Auto so a hung model cannot sit for minutes)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from app import config

_override: ContextVar[float | None] = ContextVar("llm_timeout_override", default=None)


def llm_timeout_seconds() -> float:
    return _override.get() or float(config.LLM_TIMEOUT_SECONDS)


@contextmanager
def override_llm_timeout(seconds: float | None):
    token = _override.set(seconds)
    try:
        yield
    finally:
        _override.reset(token)
