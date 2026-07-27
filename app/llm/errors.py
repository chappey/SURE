"""Map provider SDK errors to HTTP status and user-facing messages."""

from __future__ import annotations

import logging

from google.genai import errors as genai_errors

logger = logging.getLogger(__name__)

from app.llm.catalog import ModelEntry
from app.llm.fallback import AllModelsFailedError


def format_llm_error(exc: Exception, model: ModelEntry | None = None) -> tuple[int, str]:
    """Return (http_status, detail) for quiz generation failures."""
    prefix = f"{model.label}: " if model else ""

    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None) or 500
        api_message = getattr(exc, "message", None)
        if not api_message:
            response_json = getattr(exc, "details", None)
            if isinstance(response_json, dict):
                api_message = response_json.get("error", {}).get("message")

        if code == 503:
            if api_message:
                logger.warning("Gemini api_message: %s", api_message)
            return 503, prefix + "Google Gemini is temporarily unavailable due to high demand. Try another model from the dropdown."
        if code == 429:
            return 429, prefix + "Rate limit reached. Wait a moment or switch models."
        if code in (401, 403):
            return 502, prefix + "API key rejected. Check GEMINI_API_KEY in .env."
        if 500 <= code < 600:
            if api_message:
                logger.warning("Gemini api_message: %s", api_message)
            return 502, prefix + f"Provider unavailable (HTTP {code}). Try another model."
        if api_message:
            logger.warning("Gemini api_message: %s", api_message)
        return 400, prefix + f"Request rejected (HTTP {code})."

    # OpenAI SDK (OpenRouter)
    try:
        from openai import APIStatusError

        if isinstance(exc, APIStatusError):
            code = exc.status_code
            api_message = None
            if exc.response is not None:
                try:
                    body = exc.response.json()
                    api_message = body.get("error", {}).get("message")
                except Exception:
                    pass
            if code == 503:
                if api_message:
                    logger.warning("OpenRouter api_message: %s", api_message)
                return 503, prefix + "OpenRouter model is temporarily unavailable. Try another model."
            if code == 429:
                return 429, prefix + "OpenRouter rate limit reached. Try again or switch models."
            if code in (401, 403):
                return 502, prefix + "OpenRouter API key rejected. Check OPENROUTER_API_KEY in .env."
            if 500 <= code < 600:
                if api_message:
                    logger.warning("OpenRouter api_message: %s", api_message)
                return 502, prefix + f"OpenRouter unavailable (HTTP {code})."
            if api_message:
                logger.warning("OpenRouter api_message: %s", api_message)
            return 400, prefix + f"OpenRouter rejected the request (HTTP {code})."
    except ImportError:
        pass

    if isinstance(exc, AllModelsFailedError):
        return 503, exc.user_message

    if isinstance(exc, ValueError):
        return 400, str(exc)

    if isinstance(exc, RuntimeError):
        return 500, prefix + str(exc)

    return 500, prefix + "Quiz generation failed unexpectedly. Please try again or switch models."
