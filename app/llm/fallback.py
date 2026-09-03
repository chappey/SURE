from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app import config
from app.llm.catalog import ModelEntry, list_available_models
from app.llm.registry import generate_json as _generate_json
from app.llm.registry import generate_text as _generate_text
from app.llm.timeout import override_llm_timeout
from app.ops.health import prefer_healthy

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
        # Auto is the OpenRouter router (or any use_in_auto row). Free catalog
        # models are selectable explicitly and are never on this path.
        auto = [m for m in available if m.use_in_auto]
        if not auto:
            auto = [m for m in available if not m.expects_free]
        auto = prefer_healthy(auto or available)
        if not auto:
            return auto
        primary = auto[0]
        if primary.model in ("openrouter/auto", "openrouter/auto-beta"):
            return [primary] * config.AUTO_MAX_MODELS
        return auto[: config.AUTO_MAX_MODELS]
    primary = next((m for m in available if m.id == requested_id), None)
    if primary is None:
        raise ValueError(f"Model {requested_id!r} is not available.")
    rest = prefer_healthy([m for m in available if m.id != requested_id])
    return [primary] + rest


def generate_json_with_fallback(
    models: list[ModelEntry],
    prompt: str,
    schema: dict[str, Any],
    validate: Callable[[str], None] | None = None,
    *,
    timeout_seconds: float | None = None,
    allow_object_fallback: bool = True,
) -> tuple[str, ModelEntry]:
    errors: list[tuple[str, str]] = []
    for model in models:
        try:
            with override_llm_timeout(timeout_seconds):
                text = _generate_json(
                    model,
                    prompt,
                    schema,
                    allow_object_fallback=allow_object_fallback,
                )
            if not text:
                continue
            if validate is not None:
                validate(text)
            if len(models) > 1:
                logger.info(
                    "LLM fallback succeeded: %s (%s/%s)", model.id, model.provider, model.model
                )
            return text, model
        except Exception as exc:
            msg = str(exc)[:300]
            errors.append((model.id, msg))
            logger.warning(
                "LLM model failed: %s (%s/%s) — %s", model.id, model.provider, model.model, msg
            )
    _notify_all_failed(errors)
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
                    logger.info(
                        "LLM fallback succeeded: %s (%s/%s)", model.id, model.provider, model.model
                    )
                return text, model
        except Exception as exc:
            msg = str(exc)[:300]
            errors.append((model.id, msg))
            logger.warning(
                "LLM model failed: %s (%s/%s) — %s", model.id, model.provider, model.model, msg
            )
    _notify_all_failed(errors)
    raise AllModelsFailedError(errors)


def _notify_all_failed(errors: list[tuple[str, str]]) -> None:
    from app.ops import alerts

    alerts.notify(
        kind="all_models_failed",
        severity="critical",
        message="All configured AI models failed in one request: "
        + ", ".join(f"{mid} ({err[:80]})" for mid, err in errors),
    )
