"""Application settings loaded from environment / .env."""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    CANVAS_API_URL: str = ""
    CANVAS_API_TOKEN: str = ""
    CANVAS_COURSE_ID: str = ""
    CANVAS_ACCOUNT_ID: str = "1"
    CANVAS_CLIENT_ID: str = ""
    CANVAS_CLIENT_SECRET: str = ""
    CANVAS_OAUTH_REDIRECT_URI: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_HTTP_REFERER: str = ""
    OPENROUTER_APP_NAME: str = "EasyLearn"
    COURSE_EXPORT_DIR: str = ""
    SESSION_SECRET_KEY: str = "some-very-secret-key-change-in-production"

    @field_validator("CANVAS_API_URL", mode="after")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


settings = Settings()

# Paths
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CACHE_DIR = PROJECT_ROOT / "cache"
LTI_CONFIG_PATH = PROJECT_ROOT / "config" / "lti_config.json"

# Backward-compatible module-level exports (used across app/ and utils/)
CANVAS_API_URL = settings.CANVAS_API_URL
CANVAS_API_TOKEN = settings.CANVAS_API_TOKEN
CANVAS_COURSE_ID = settings.CANVAS_COURSE_ID
CANVAS_ACCOUNT_ID = settings.CANVAS_ACCOUNT_ID
CANVAS_CLIENT_ID = settings.CANVAS_CLIENT_ID
CANVAS_CLIENT_SECRET = settings.CANVAS_CLIENT_SECRET
CANVAS_OAUTH_REDIRECT_URI = settings.CANVAS_OAUTH_REDIRECT_URI
GEMINI_API_KEY = settings.GEMINI_API_KEY
GEMINI_MODEL = settings.GEMINI_MODEL
OPENROUTER_API_KEY = settings.OPENROUTER_API_KEY
OPENROUTER_HTTP_REFERER = settings.OPENROUTER_HTTP_REFERER
OPENROUTER_APP_NAME = settings.OPENROUTER_APP_NAME
COURSE_EXPORT_DIR = settings.COURSE_EXPORT_DIR
SESSION_SECRET_KEY = settings.SESSION_SECRET_KEY
