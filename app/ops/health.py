"""Per-model circuit breaker plus OpenRouter account snapshot."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

from app import config
from app.llm.catalog import ModelEntry
from app.ops import alerts

logger = logging.getLogger(__name__)

OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"


@dataclass
class Circuit:
    failures: int = 0
    opened_at: float = 0.0
    last_error: str = ""
    last_change_ts: float = 0.0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0


_lock = threading.Lock()
_circuits: dict[str, Circuit] = {}
_provider_status: dict[str, dict[str, Any]] = {}


def reset() -> None:
    """Clear in-memory health (tests)."""
    with _lock:
        _circuits.clear()
        _provider_status.clear()


def _threshold() -> int:
    return max(1, int(config.MODEL_CIRCUIT_FAILURES))


def _open_seconds() -> float:
    return float(config.MODEL_CIRCUIT_OPEN_SECONDS)


def _circuit(model_id: str) -> Circuit:
    if model_id not in _circuits:
        _circuits[model_id] = Circuit()
    return _circuits[model_id]


def is_open(model_id: str, now: float | None = None) -> bool:
    now = now or time.time()
    with _lock:
        c = _circuits.get(model_id)
        if c is None or c.opened_at <= 0:
            return False
        if now - c.opened_at >= _open_seconds():
            # Half-open: allow one probe.
            return False
        return True


def record_success(model_id: str) -> None:
    with _lock:
        c = _circuit(model_id)
        was_open = c.opened_at > 0
        c.failures = 0
        c.opened_at = 0.0
        c.last_error = ""
        c.last_success_ts = time.time()
        c.last_change_ts = c.last_success_ts
    if was_open:
        alerts.notify(
            kind=f"model_recovered:{model_id}",
            severity="info",
            message=f"Model {model_id} recovered after circuit-open period.",
        )


def record_failure(model_id: str, error: str, *, counts: bool = True) -> None:
    if not counts:
        return
    opened = False
    with _lock:
        c = _circuit(model_id)
        c.failures += 1
        c.last_error = (error or "")[:300]
        c.last_failure_ts = time.time()
        c.last_change_ts = c.last_failure_ts
        if c.failures >= _threshold() and c.opened_at <= 0:
            c.opened_at = c.last_failure_ts
            opened = True
    if opened:
        alerts.notify(
            kind=f"model_down:{model_id}",
            severity="critical",
            message=(
                f"Model {model_id} circuit opened after {_threshold()} consecutive "
                f"provider failures. Last error: {error[:200]}"
            ),
        )


def prefer_healthy(models: list[ModelEntry]) -> list[ModelEntry]:
    """Keep models with an open circuit out of the fallback list when alternatives exist."""
    up = [m for m in models if not is_open(m.id)]
    return up if up else list(models)


def model_states(catalog: list[ModelEntry]) -> list[dict[str, Any]]:
    now = time.time()
    out: list[dict[str, Any]] = []
    with _lock:
        for entry in catalog:
            c = _circuits.get(entry.id) or Circuit()
            opened = c.opened_at > 0 and (now - c.opened_at) < _open_seconds()
            if opened:
                status = "down"
            elif c.failures > 0:
                status = "degraded"
            else:
                status = "up"
            out.append(
                {
                    "id": entry.id,
                    "label": entry.label,
                    "provider": entry.provider,
                    "model": entry.model,
                    "status": status,
                    "consecutive_failures": c.failures,
                    "circuit_open": opened,
                    "last_error": c.last_error,
                    "last_success_ts": c.last_success_ts or None,
                    "last_failure_ts": c.last_failure_ts or None,
                }
            )
    return out


def set_provider_status(provider: str, **fields: Any) -> None:
    with _lock:
        prev = _provider_status.get(provider) or {}
        status = {
            **prev,
            **fields,
            "checked_at": time.time(),
        }
        _provider_status[provider] = status
        became_down = prev.get("ok") is True and fields.get("ok") is False
        became_up = prev.get("ok") is False and fields.get("ok") is True
    if became_down:
        alerts.notify(
            kind=f"provider_down:{provider}",
            severity="critical",
            message=f"{provider} API is unreachable or rejecting the key: {fields.get('error', '')}",
        )
    elif became_up:
        alerts.notify(
            kind=f"provider_recovered:{provider}",
            severity="info",
            message=f"{provider} API is reachable again.",
        )


def provider_snapshot() -> dict[str, Any]:
    with _lock:
        return {k: dict(v) for k, v in _provider_status.items()}


def _public_key_label(label: str) -> str:
    raw = (label or "").strip()
    if not raw or raw.startswith("sk-") or raw.lower().startswith("or-"):
        return "API key"
    return raw


def refresh_openrouter_account() -> dict[str, Any]:
    api_key = (config.OPENROUTER_API_KEY or "").strip()
    if not api_key:
        status = {"configured": False, "ok": False, "error": "OPENROUTER_API_KEY not set"}
        set_provider_status("openrouter", **status)
        return status
    try:
        response = requests.get(
            OPENROUTER_KEY_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if response.status_code >= 400:
            status = {
                "configured": True,
                "ok": False,
                "error": f"HTTP {response.status_code}",
            }
            set_provider_status("openrouter", **status)
            return status
        data = (response.json() or {}).get("data") or {}
        limit = data.get("limit")
        remaining = data.get("limit_remaining")
        status = {
            "configured": True,
            "ok": True,
            "error": "",
            "label": _public_key_label(str(data.get("label") or "")),
            "limit": limit,
            "limit_remaining": remaining,
            "usage": data.get("usage"),
            "is_free_tier": data.get("is_free_tier"),
            "rate_limit": data.get("rate_limit"),
        }
        set_provider_status("openrouter", **status)
        if isinstance(limit, (int, float)) and isinstance(remaining, (int, float)) and limit > 0:
            ratio = remaining / limit
            if ratio <= 0.05:
                alerts.notify(
                    kind="openrouter_credits_critical",
                    severity="critical",
                    message=f"OpenRouter credits nearly exhausted: ${remaining:.4f} of ${limit:.2f} remaining.",
                )
            elif ratio <= 0.2:
                alerts.notify(
                    kind="openrouter_credits_low",
                    severity="warning",
                    message=f"OpenRouter credits low: ${remaining:.4f} of ${limit:.2f} remaining.",
                )
        return status
    except Exception as exc:
        status = {"configured": True, "ok": False, "error": str(exc)[:200]}
        set_provider_status("openrouter", **status)
        return status
