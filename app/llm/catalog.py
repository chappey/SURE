"""Load and validate the curated AI model catalog."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel

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
    expects_free: bool = False
    use_in_auto: bool = False
    show_in_picker: bool = False
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


def list_available_models() -> list[ModelEntry]:
    """Catalog entries whose provider API key is configured."""
    return [e for e in load_catalog() if _provider_configured(e.provider)]


def resolve_auto_model() -> ModelEntry:
    """Pick the default catalog model if available, else the first with a configured key."""
    available = list_available_models()
    if not available:
        raise ValueError(
            "No AI provider is configured. Set OPENROUTER_API_KEY and/or GEMINI_API_KEY in .env."
        )
    for entry in available:
        if entry.default:
            return entry
    # Prefer catalog order among available (default may be missing a key).
    by_id = {e.id: e for e in available}
    for entry in load_catalog():
        if entry.id in by_id:
            return by_id[entry.id]
    return available[0]


def resolve_model(model_id: str | None) -> ModelEntry:
    """Resolve an explicit model id, or auto-select when ``model_id`` is empty."""
    if not (model_id or "").strip():
        return resolve_auto_model()
    chosen = model_id.strip()
    for entry in load_catalog():
        if entry.id == chosen:
            if not _provider_configured(entry.provider):
                raise ValueError(
                    f"Model {entry.label!r} is not available: "
                    f"{entry.provider} API key is not configured on the server."
                )
            return entry
    raise ValueError(f"Unknown model_id: {chosen!r}")


def list_models_for_api() -> dict[str, Any]:
    """Catalog payload for the dashboard, including auto-selection helpers."""
    models: list[dict[str, Any]] = []
    for entry in load_catalog():
        if not entry.show_in_picker:
            continue
        available = _provider_configured(entry.provider)
        models.append(
            {
                "id": entry.id,
                "label": entry.label,
                "provider": entry.provider,
                "default": entry.default,
                "expects_free": entry.expects_free,
                "structured_output": entry.structured_output,
                "available": available,
            }
        )
    auto_id: str | None = None
    auto_label: str | None = None
    try:
        auto = resolve_auto_model()
        auto_id = auto.id
        auto_label = auto.label
    except ValueError:
        pass
    return {
        "models": models,
        "auto_model_id": auto_id,
        "auto_model_label": auto_label,
    }
