"""Load and validate the curated AI model catalog."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import config

CATALOG_PATH = config.PROJECT_ROOT / "config" / "ai_models.json"

ProviderName = Literal["gemini", "openrouter"]
StructuredOutputMode = Literal["native", "best_effort"]


class ModelEntry(BaseModel):
    id: str
    label: str
    provider: ProviderName
    model: str
    default: bool = False
    structured_output: StructuredOutputMode = "native"


def _provider_configured(provider: ProviderName) -> bool:
    if provider == "gemini":
        return bool(config.GEMINI_API_KEY.strip())
    if provider == "openrouter":
        return bool(config.OPENROUTER_API_KEY.strip())
    return False


@lru_cache(maxsize=1)
def load_catalog() -> list[ModelEntry]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"Model catalog not found: {CATALOG_PATH}")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    entries = [ModelEntry.model_validate(item) for item in data]
    if not entries:
        raise ValueError("Model catalog is empty")
    return entries


def get_default_model_id() -> str:
    entries = load_catalog()
    for entry in entries:
        if entry.default:
            return entry.id
    return entries[0].id


def resolve_model(model_id: str | None) -> ModelEntry:
    entries = load_catalog()
    chosen = model_id or get_default_model_id()
    for entry in entries:
        if entry.id == chosen:
            if not _provider_configured(entry.provider):
                raise ValueError(
                    f"Model {entry.label!r} is not available: "
                    f"{entry.provider} API key is not configured on the server."
                )
            return entry
    raise ValueError(f"Unknown model_id: {chosen!r}")


def list_models_for_api() -> list[dict[str, Any]]:
    """Catalog entries for the dashboard, including availability flags."""
    results: list[dict[str, Any]] = []
    for entry in load_catalog():
        available = _provider_configured(entry.provider)
        results.append(
            {
                "id": entry.id,
                "label": entry.label,
                "provider": entry.provider,
                "default": entry.default,
                "structured_output": entry.structured_output,
                "available": available,
            }
        )
    return results
