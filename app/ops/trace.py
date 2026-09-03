"""Wrap a single provider HTTP call: budget gate, timing, ledger, circuit."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from openai import APIStatusError

from app.llm.catalog import ModelEntry
from app.ops import budgets, context, health, ledger

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _safe_record(**fields: Any) -> None:
    try:
        ledger.record_call(**fields)
    except Exception:
        logger.exception("Failed to persist LLM ledger row")


def _http_status(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    return None


def counts_as_outage(exc: BaseException) -> bool:
    """True for downtime / rate-limit / transport failures, not schema 400s."""
    status = _http_status(exc)
    if status in (401, 403, 408, 429) or (status is not None and status >= 500):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    name = type(exc).__name__.lower()
    if "timeout" in name or "connection" in name or "ratelimit" in name:
        return True
    return False


def usage_from_openai(response: Any) -> dict[str, Any]:
    dumped: dict[str, Any] = {}
    if hasattr(response, "model_dump"):
        try:
            dumped = response.model_dump() or {}
        except Exception:
            dumped = {}
    usage = dumped.get("usage") or {}
    if not usage:
        raw = getattr(response, "usage", None)
        if raw is None:
            usage = {}
        elif isinstance(raw, dict):
            usage = raw
        else:
            extra = getattr(raw, "model_extra", None) or {}
            usage = {
                "prompt_tokens": getattr(raw, "prompt_tokens", None),
                "completion_tokens": getattr(raw, "completion_tokens", None),
                "total_tokens": getattr(raw, "total_tokens", None),
                "cost": getattr(raw, "cost", None) or extra.get("cost"),
            }
    cost = usage.get("cost")
    if cost is None:
        details = usage.get("cost_details") or {}
        if isinstance(details, dict):
            cost = details.get("upstream_inference_cost")
    return {
        "prompt_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
        "completion_tokens": usage.get("completion_tokens") or usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cost_usd": float(cost) if isinstance(cost, (int, float)) else None,
        "generation_id": dumped.get("id") or getattr(response, "id", None),
        "model": dumped.get("model") or getattr(response, "model", None),
    }


def usage_from_gemini(response: Any) -> dict[str, Any]:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {}
    prompt = getattr(meta, "prompt_token_count", None)
    completion = getattr(meta, "candidates_token_count", None)
    total = getattr(meta, "total_token_count", None)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_usd": None,
        "generation_id": getattr(response, "response_id", None) or "",
    }


def run_llm_call(
    model: ModelEntry,
    mode: str,
    fn: Callable[[], T],
    *,
    prompt_chars: int = 0,
    usage_from: Callable[[T], dict[str, Any]] | None = None,
    health_on_failure: bool | None = None,
) -> T:
    """Execute ``fn``, enforce budget, and persist a ledger row."""
    ident = context.snapshot()
    budgets.assert_within_budget(ident.get("user_id") or None)

    t0 = time.perf_counter()
    try:
        result = fn()
        latency_ms = (time.perf_counter() - t0) * 1000
        usage: dict[str, Any] = {}
        if usage_from:
            try:
                usage = usage_from(result) or {}
            except Exception:
                logger.exception("Failed to parse LLM usage")
        _safe_record(
            request_id=ident.get("request_id"),
            user_id=ident.get("user_id"),
            user_name=ident.get("user_name"),
            course_id=ident.get("course_id"),
            purpose=ident.get("purpose"),
            provider=model.provider,
            model_id=model.id,
            model=usage.get("model") or model.model,
            mode=mode,
            success=True,
            latency_ms=latency_ms,
            prompt_chars=prompt_chars,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            cost_usd=usage.get("cost_usd"),
            generation_id=usage.get("generation_id") or "",
        )
        health.record_success(model.id)
        logger.info(
            "LLM ok model=%s mode=%s latency_ms=%.0f tokens=%s cost=%s user=%s",
            model.id,
            mode,
            latency_ms,
            usage.get("total_tokens"),
            usage.get("cost_usd"),
            ident.get("user_id") or "-",
        )
        return result
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        err = str(exc)[:300]
        _safe_record(
            request_id=ident.get("request_id"),
            user_id=ident.get("user_id"),
            user_name=ident.get("user_name"),
            course_id=ident.get("course_id"),
            purpose=ident.get("purpose"),
            provider=model.provider,
            model_id=model.id,
            model=model.model,
            mode=mode,
            success=False,
            error=err,
            latency_ms=latency_ms,
            prompt_chars=prompt_chars,
        )
        trip = counts_as_outage(exc) if health_on_failure is None else health_on_failure
        health.record_failure(model.id, err, counts=trip)
        if isinstance(exc, APIStatusError) and exc.status_code in (401, 403):
            alerts_provider_auth(model.provider, err)
        raise


def alerts_provider_auth(provider: str, error: str) -> None:
    from app.ops import alerts

    alerts.notify(
        kind=f"provider_auth:{provider}",
        severity="critical",
        message=f"{provider} API key rejected: {error[:200]}",
    )
