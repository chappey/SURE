from __future__ import annotations

import logging
from typing import Any

from app.llm.catalog import ModelEntry, list_available_models
from app.llm.registry import generate_json as _generate_json
from app.llm.registry import generate_text as _generate_text

logger = logging.getLogger(__name__)


class AllModelsFailedError(Exception):
    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = errors
        super().__init__(f"All {len(errors)} model(s) failed: {', '.join(e[0] for e in errors)}")

    @property
    def user_message(self) -> str:
        return (
            "Quiz generation failed after trying all available AI models. "
            "Please try again or select a specific model from the dropdown."
        )


def fallback_models(requested_id: str | None = None) -> list[ModelEntry]:
    available = list_available_models()
    if not available:
        raise ValueError("No AI models are available. Check your API keys.")
    if requested_id is None:
        return available
    primary = next((m for m in available if m.id == requested_id), None)
    if primary is None:
        raise ValueError(f"Model {requested_id!r} is not available.")
    return [primary] + [m for m in available if m.id != requested_id]


def generate_json_with_fallback(
    models: list[ModelEntry],
    prompt: str,
    schema: dict[str, Any],
) -> tuple[str, ModelEntry]:
    errors: list[tuple[str, str]] = []
    for model in models:
        try:
            text = _generate_json(model, prompt, schema)
            if text:
                if len(models) > 1:
                    logger.info("Auto fallback succeeded with %s (%s)", model.label, model.id)
                return text, model
        except Exception as exc:
            msg = str(exc)[:300]
            errors.append((model.id, msg))
            logger.warning("Model %s (%s) failed: %s", model.label, model.id, msg)
    raise AllModelsFailedError(errors)


def generate_text_with_fallback(
    models: list[ModelEntry],
    prompt: str,
) -> tuple[str, ModelEntry]:
    errors: list[tuple[str, str]] = []
    for model in models:
        try:
            text = _generate_text(model, prompt)
            if text:
                if len(models) > 1:
                    logger.info("Auto fallback succeeded with %s (%s)", model.label, model.id)
                return text, model
        except Exception as exc:
            msg = str(exc)[:300]
            errors.append((model.id, msg))
            logger.warning("Model %s (%s) failed: %s", model.label, model.id, msg)
    raise AllModelsFailedError(errors)
