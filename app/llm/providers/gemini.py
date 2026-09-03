"""Google Gemini via native google-genai SDK."""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import types

from app import config
from app.llm.catalog import ModelEntry
from app.llm.timeout import llm_timeout_seconds
from app.ops.trace import run_llm_call, usage_from_gemini

logger = logging.getLogger(__name__)


def _client():
    api_key = config.GEMINI_API_KEY.strip()
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY in .env (https://aistudio.google.com/apikey)")
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=int(llm_timeout_seconds() * 1000)),
    )


def generate_json(model: ModelEntry, prompt: str, schema: dict[str, Any]) -> str:
    logger.info("Gemini requesting: model=%s", model.model)
    client = _client()

    def _call():
        return client.models.generate_content(
            model=model.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )

    response = run_llm_call(
        model,
        "json",
        _call,
        prompt_chars=len(prompt),
        usage_from=usage_from_gemini,
    )
    text = response.text
    if not text:
        raise RuntimeError("Gemini returned empty response")
    return text


def generate_text(model: ModelEntry, prompt: str) -> str:
    logger.info("Gemini requesting: model=%s", model.model)
    client = _client()

    def _call():
        return client.models.generate_content(
            model=model.model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.4),
        )

    response = run_llm_call(
        model,
        "text",
        _call,
        prompt_chars=len(prompt),
        usage_from=usage_from_gemini,
    )
    text = response.text
    if not text:
        raise RuntimeError("Gemini returned empty response")
    return text
