"""Google Gemini via native google-genai SDK."""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import types

from app import config
from app.llm.catalog import ModelEntry

logger = logging.getLogger(__name__)


def generate_json(model: ModelEntry, prompt: str, schema: dict[str, Any]) -> str:
    api_key = config.GEMINI_API_KEY.strip()
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY in .env (https://aistudio.google.com/apikey)")

    logger.info("Gemini requesting: model=%s", model.model)
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model.model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )
    text = response.text
    if not text:
        raise RuntimeError("Gemini returned empty response")
    return text


def generate_text(model: ModelEntry, prompt: str) -> str:
    api_key = config.GEMINI_API_KEY.strip()
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY in .env (https://aistudio.google.com/apikey)")

    logger.info("Gemini requesting: model=%s", model.model)
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model.model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.4),
    )
    text = response.text
    if not text:
        raise RuntimeError("Gemini returned empty response")
    return text
