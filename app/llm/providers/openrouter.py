"""OpenRouter via OpenAI-compatible chat completions API."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any

from httpx import Timeout
from openai import OpenAI

from app import config
from app.llm.catalog import ModelEntry
from app.llm.schema_utils import prepare_openrouter_schema
from app.llm.timeout import llm_timeout_seconds
from app.ops.trace import run_llm_call, usage_from_openai

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_AUTO_SLUGS = frozenset({"openrouter/auto", "openrouter/auto-beta"})
_last_routed_model: ContextVar[str | None] = ContextVar("or_routed_model", default=None)


def last_routed_model() -> str | None:
    return _last_routed_model.get()


def is_auto_router(slug: str) -> bool:
    return slug in _AUTO_SLUGS


def auto_router_extra_body(slug: str) -> dict[str, Any]:
    """Plugin payload for openrouter/auto. Never send cost_quality_tradeoff."""
    if not is_auto_router(slug):
        return {}
    plugin_id = "auto-beta-router" if slug.endswith("auto-beta") else "auto-router"
    return {
        "plugins": [
            {
                "id": plugin_id,
                "cost_tier": config.AUTO_ROUTER_COST_TIER,
                "excluded_models": ["*:free", "openrouter/free"],
            }
        ],
        # Steer the routed model toward fast endpoints; soft preference, not a filter.
        "provider": {"sort": "throughput", "preferred_min_throughput": 60},
    }


def _strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _parse_json_object_str(text: str) -> str:
    cleaned = _strip_code_fences(text)
    # Extract JSON object between first { and last }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except (ValueError, json.JSONDecodeError):
            pass
    try:
        json.loads(cleaned)
        return cleaned
    except Exception:
        if start != -1 and end != -1 and end > start:
            return cleaned[start : end + 1]
        return cleaned


def _client() -> OpenAI:
    api_key = config.OPENROUTER_API_KEY.strip()
    if not api_key:
        raise RuntimeError("Set OPENROUTER_API_KEY in .env (https://openrouter.ai/keys)")

    default_headers: dict[str, str] = {}
    if config.OPENROUTER_HTTP_REFERER:
        default_headers["HTTP-Referer"] = config.OPENROUTER_HTTP_REFERER
    if config.OPENROUTER_APP_NAME:
        default_headers["X-Title"] = config.OPENROUTER_APP_NAME

    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key,
        default_headers=default_headers or None,
        timeout=Timeout(llm_timeout_seconds(), connect=10.0),
    )


def _extract_message_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("OpenRouter returned empty response")
    message = getattr(choices[0], "message", None)
    text = getattr(message, "content", None) if message is not None else None
    if not text:
        raise RuntimeError("OpenRouter returned empty response")
    return text


def _create(client: OpenAI, model_slug: str | None = None, **kwargs: Any):
    # Ask OpenRouter to include native cost so the ledger can cap spend.
    extra_body = dict(kwargs.pop("extra_body", None) or {})
    extra_body["usage"] = {"include": True}
    extra_body.update(auto_router_extra_body(model_slug or kwargs.get("model") or ""))
    extra_body.pop("cost_quality_tradeoff", None)
    return client.chat.completions.create(extra_body=extra_body, **kwargs)


def generate_json(
    model: ModelEntry,
    prompt: str,
    schema: dict[str, Any],
    *,
    allow_object_fallback: bool = True,
) -> str:
    client = _client()
    prepared_schema = prepare_openrouter_schema(schema)

    logger.info("OpenRouter requesting: model=%s (mode=json_schema)", model.model)
    try:
        response = run_llm_call(
            model,
            "json_schema",
            lambda: _create(
                client,
                model=model.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "weekly_quiz",
                        "strict": True,
                        "schema": prepared_schema,
                    },
                },
            ),
            prompt_chars=len(prompt),
            usage_from=usage_from_openai,
        )
        text = _extract_message_text(response)
        _last_routed_model.set(getattr(response, "model", None) or None)
        return _parse_json_object_str(text)
    except Exception as schema_exc:
        if not allow_object_fallback:
            raise
        logger.warning(
            "OpenRouter json_schema failed for model %s (%s), falling back to json_object",
            model.id,
            schema_exc,
        )

    json_prompt = (
        prompt
        + "\n\nRespond with ONLY valid JSON matching the WeeklyQuiz schema. "
        "No markdown fences, no commentary."
    )
    response = run_llm_call(
        model,
        "json_object",
        lambda: _create(
            client,
            model=model.model,
            messages=[{"role": "user", "content": json_prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        ),
        prompt_chars=len(json_prompt),
        usage_from=usage_from_openai,
    )
    text = _extract_message_text(response).strip()
    _last_routed_model.set(getattr(response, "model", None) or None)
    # Tolerate fences / trailing prose from smaller free models
    try:
        return _parse_json_object_str(text)
    except (ValueError, json.JSONDecodeError):
        cleaned = _strip_code_fences(text)
        json.loads(cleaned)  # validate
        return cleaned


def generate_text(model: ModelEntry, prompt: str) -> str:
    client = _client()
    logger.info("OpenRouter requesting: model=%s (mode=text)", model.model)
    response = run_llm_call(
        model,
        "text",
        lambda: _create(
            client,
            model=model.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        ),
        prompt_chars=len(prompt),
        usage_from=usage_from_openai,
    )
    text = _extract_message_text(response)
    _last_routed_model.set(getattr(response, "model", None) or None)
    return text
