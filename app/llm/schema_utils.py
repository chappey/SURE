"""Prepare JSON Schema for OpenRouter strict structured outputs."""

from __future__ import annotations

import copy
from typing import Any


def prepare_openrouter_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of schema suitable for OpenRouter json_schema strict mode."""
    prepared = copy.deepcopy(schema)
    prepared.setdefault("additionalProperties", False)
    _ensure_additional_properties_false(prepared)
    return prepared


def _ensure_additional_properties_false(node: Any) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") == "object":
        node.setdefault("additionalProperties", False)
    for key in ("properties", "$defs", "definitions", "patternProperties"):
        value = node.get(key)
        if isinstance(value, dict):
            for child in value.values():
                _ensure_additional_properties_false(child)
    for key in ("items", "additionalProperties", "contains", "not"):
        value = node.get(key)
        if isinstance(value, dict):
            _ensure_additional_properties_false(value)
        elif isinstance(value, list):
            for item in value:
                _ensure_additional_properties_false(item)
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        for item in node.get(key, []) or []:
            _ensure_additional_properties_false(item)
