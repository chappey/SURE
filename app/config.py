"""Application settings loaded from environment / .env."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, urlunparse

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
    CANVAS_CLIENT_ID: str = ""
    CANVAS_CLIENT_SECRET: str = ""
    CANVAS_OAUTH_REDIRECT_URI: str = ""
    # Space-separated Canvas API scopes — only when the OAuth key enforces scopes.
    CANVAS_OAUTH_SCOPES: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_HTTP_REFERER: str = ""
    OPENROUTER_APP_NAME: str = "EasyLearn"
    SESSION_SECRET_KEY: str = ""
    CANVAS_PUBLIC_URL: str = ""
    EASYLEARN_PUBLIC_URL: str = ""
    RAG_ENABLED: bool = False
    OCR_ENABLED: bool = False
    RAG_MAX_TOKENS: int = 12000



    @field_validator("SESSION_SECRET_KEY", mode="after")
    @classmethod
    def reject_insecure_default(cls, v: str) -> str:
        if not v.strip() or v.strip() == "some-very-secret-key-change-in-production":
            raise ValueError(
                "SESSION_SECRET_KEY must be set to a random 64-char hex string. "
                "Generate one:  python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    @field_validator("CANVAS_API_URL", mode="after")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


settings = Settings()


def _local_http_lti(url: str) -> bool:
    """True when Canvas is served over plain HTTP (local Docker dev)."""
    return url.startswith("http://")


# Keep SameSite=None for cross-site POST to /launch; omit Secure on HTTP dev hosts.
LOCAL_HTTP_LTI = _local_http_lti(settings.CANVAS_API_URL)
SESSION_HTTPS_ONLY = not LOCAL_HTTP_LTI
# For plain-HTTP local development (common with Canvas in Docker), use Lax cookies.
# On public HTTPS, use None+Secure for cross-site LTI POSTs.
SESSION_SAME_SITE: str = "lax" if LOCAL_HTTP_LTI else "none"


def _effective_canvas_public() -> str:
    explicit = settings.CANVAS_PUBLIC_URL.strip()
    if explicit:
        return explicit.rstrip("/")
    # Default to the API URL. For local Docker Canvas setups that use a different
    # browser-facing hostname (e.g. canvas.docker), set CANVAS_PUBLIC_URL explicitly.
    return settings.CANVAS_API_URL.rstrip("/")


def _effective_easylearn_public() -> str:
    explicit = settings.EASYLEARN_PUBLIC_URL.strip()
    if explicit:
        return explicit.rstrip("/")
    # Derive from the Canvas public hostname on a conventional port.
    # For custom ports or different host, set EASYLEARN_PUBLIC_URL explicitly.
    host = urlparse(_effective_canvas_public()).hostname or "localhost"
    scheme = "https" if not _local_http_lti(settings.CANVAS_API_URL) else "http"
    return f"{scheme}://{host}:8000"


CANVAS_PUBLIC_URL = _effective_canvas_public()
EASYLEARN_PUBLIC_URL = _effective_easylearn_public()


def canvas_quiz_url(course_id: int | str, canvas_quiz_id: int | str) -> str:
    """Browser-facing Canvas quiz link, derived from the configured public domain.

    Single source of truth for quiz URLs. Always computed — never persisted —
    so the link follows CANVAS_PUBLIC_URL even if the domain changes later.
    """
    return f"{CANVAS_PUBLIC_URL.rstrip('/')}/courses/{course_id}/quizzes/{canvas_quiz_id}"


_OAUTH_PLACEHOLDER_VALUES = frozenset(
    {
        "your_canvas_api_developer_key_client_id",
        "your_canvas_api_developer_key_client_secret",
    }
)


def oauth_enabled() -> bool:
    client_id = settings.CANVAS_CLIENT_ID.strip()
    client_secret = settings.CANVAS_CLIENT_SECRET.strip()
    if not client_id or not client_secret:
        return False
    if client_id.lower() in _OAUTH_PLACEHOLDER_VALUES:
        return False
    if client_secret.lower() in _OAUTH_PLACEHOLDER_VALUES:
        return False
    return True


def effective_oauth_redirect_uri() -> str:
    explicit = settings.CANVAS_OAUTH_REDIRECT_URI.strip()
    if explicit:
        return explicit.rstrip("/")
    return f"{EASYLEARN_PUBLIC_URL.rstrip('/')}/oauth/callback"


CANVAS_OAUTH_REDIRECT_URI_EFFECTIVE = effective_oauth_redirect_uri()


def rewrite_tool_url(url: str) -> str:
    """Map localhost tool URLs to EASYLEARN_PUBLIC_URL so OIDC stays on one site."""
    if not url:
        return url
    parsed = urlparse(url)
    public = urlparse(EASYLEARN_PUBLIC_URL)
    if parsed.hostname in ("localhost", "127.0.0.1") and public.hostname:
        return urlunparse(
            parsed._replace(scheme=public.scheme or parsed.scheme, netloc=public.netloc)
        )
    return url


def rewrite_canvas_url(url: str) -> str:
    """Map localhost Canvas URLs to CANVAS_PUBLIC_URL for OIDC authorize."""
    if not url:
        return url
    parsed = urlparse(url)
    public = urlparse(CANVAS_PUBLIC_URL)
    if parsed.hostname in ("localhost", "127.0.0.1") and public.hostname:
        return urlunparse(
            parsed._replace(scheme=public.scheme or parsed.scheme, netloc=public.netloc)
        )
    return url

# Paths
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CACHE_DIR = PROJECT_ROOT / "cache"
# Instance-specific login dumps (gitignored via cache/). Never commit these.
CREDS_DIR = CACHE_DIR / "credentials"
LTI_CONFIG_PATH = PROJECT_ROOT / "config" / "lti_config.json"

# Backward-compatible module-level exports (used across app/ and utils/)
CANVAS_API_URL = settings.CANVAS_API_URL
CANVAS_API_TOKEN = settings.CANVAS_API_TOKEN
CANVAS_CLIENT_ID = settings.CANVAS_CLIENT_ID
CANVAS_CLIENT_SECRET = settings.CANVAS_CLIENT_SECRET
CANVAS_OAUTH_REDIRECT_URI = settings.CANVAS_OAUTH_REDIRECT_URI
CANVAS_OAUTH_SCOPES = settings.CANVAS_OAUTH_SCOPES
GEMINI_API_KEY = settings.GEMINI_API_KEY
GEMINI_MODEL = settings.GEMINI_MODEL
OPENROUTER_API_KEY = settings.OPENROUTER_API_KEY
OPENROUTER_HTTP_REFERER = settings.OPENROUTER_HTTP_REFERER
OPENROUTER_APP_NAME = settings.OPENROUTER_APP_NAME
SESSION_SECRET_KEY = settings.SESSION_SECRET_KEY
RAG_ENABLED = settings.RAG_ENABLED
OCR_ENABLED = settings.OCR_ENABLED
RAG_MAX_TOKENS = settings.RAG_MAX_TOKENS
