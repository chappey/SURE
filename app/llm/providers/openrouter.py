"""OpenRouter via OpenAI-compatible chat completions API."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from app import config
from app.llm.catalog import ModelEntry
from app.llm.schema_utils import prepare_openrouter_schema

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start : end + 1]
        json.loads(candidate)
        return candidate
    json.loads(cleaned)
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
    )


def _extract_message_text(response) -> str:
    text = response.choices[0].message.content
    if not text:
        raise RuntimeError("OpenRouter returned empty response")
    return text


def generate_json(model: ModelEntry, prompt: str, schema: dict[str, Any]) -> str:
    client = _client()
    prepared_schema = prepare_openrouter_schema(schema)

    logger.info("OpenRouter requesting: model=%s (mode=json_schema)", model.model)
    try:
        response = client.chat.completions.create(
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
        )
        return _extract_message_text(response)
    except Exception as schema_exc:
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
    response = client.chat.completions.create(
        model=model.model,
        messages=[{"role": "user", "content": json_prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    text = _extract_message_text(response).strip()
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
    response = client.chat.completions.create(
        model=model.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    return _extract_message_text(response)
