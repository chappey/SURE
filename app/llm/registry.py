"""Dispatch LLM generation to the configured provider."""

from __future__ import annotations

from typing import Any

from app.llm.catalog import ModelEntry, ProviderName
from app.llm.providers import gemini, openrouter


def generate_json(
    model: ModelEntry,
    prompt: str,
    schema: dict[str, Any],
    *,
    allow_object_fallback: bool = True,
) -> str:
    provider: ProviderName = model.provider
    if provider == "gemini":
        return gemini.generate_json(model, prompt, schema)
    if provider == "openrouter":
        return openrouter.generate_json(
            model, prompt, schema, allow_object_fallback=allow_object_fallback
        )
    raise ValueError(f"Unsupported provider: {provider}")


def generate_text(model: ModelEntry, prompt: str) -> str:
    provider: ProviderName = model.provider
    if provider == "gemini":
        return gemini.generate_text(model, prompt)
    if provider == "openrouter":
        return openrouter.generate_text(model, prompt)
    raise ValueError(f"Unsupported provider: {provider}")
