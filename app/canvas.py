"""Shared Canvas API client."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from urllib.parse import urlparse

import requests
from canvasapi import Canvas

from . import config

logger = logging.getLogger("easylearn")


def get_canvas(token: str | None = None) -> Canvas:
    """Return a configured Canvas client using the provided token or config fallback."""
    url = config.CANVAS_API_URL
    api_token = token or config.CANVAS_API_TOKEN

    if not url or not api_token:
        raise ValueError("Canvas API URL or Token is missing in configuration.")

    if url.startswith("http://") and ("localhost" in url or "127.0.0.1" in url):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Canvas may respond unexpectedly",
                category=UserWarning,
            )
            canvas = Canvas(url, api_token)
    else:
        canvas = Canvas(url, api_token)

    requester = getattr(canvas, "_Canvas__requester", None)
    session = getattr(requester, "_session", None)
    if session is not None:
        session.headers.update(
            {
                "User-Agent": "EasyLearn/0.1.0 (LTI Quiz Generator)"
            }
        )

    return canvas


def _get_internal_host() -> str:
    """Return the internal hostname to use for Host headers in local dev, if any."""
    if not config.LOCAL_HTTP_LTI:
        return ""
    env_host = (config.CANVAS_INTERNAL_HOST or "").strip()
    if env_host:
        return env_host
    try:
        h = urlparse(config.CANVAS_API_URL).hostname or ""
        if "docker" in h.lower():
            return h
    except Exception:
        pass
    return ""


def download_canvas_file(canvas_client, file_obj, dest_path: str | Path, token: str | None = None) -> None:
    """Download a Canvas file, handling local Docker networking redirect loops when needed."""
    dest_path = Path(dest_path)
    api_token = token or config.CANVAS_API_TOKEN
    headers: dict[str, str] = {}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    url = file_obj.url
    internal_host = _get_internal_host()
    if internal_host and any(x in url for x in ("localhost:3000", "127.0.0.1:3000", internal_host)):
        headers["Host"] = internal_host

    try:
        session = requests.Session()
        current_url = url
        for i in range(10):
            req_headers = headers.copy() if i == 0 else {}
            if "Host" in headers:
                req_headers["Host"] = headers["Host"]

            resp = session.get(current_url, headers=req_headers, allow_redirects=False, timeout=60)
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location")
                if not loc:
                    break
                # If we have an internal host, rewrite common local redirect patterns to include port 3000.
                if internal_host:
                    current_url = (
                        loc.replace(f"://{internal_host}/", f"://{internal_host}:3000/")
                        .replace(f"://{internal_host}:80/", f"://{internal_host}:3000/")
                    )
                else:
                    current_url = (
                        loc.replace("://localhost/", "://localhost:3000/")
                        .replace("://127.0.0.1/", "://127.0.0.1:3000/")
                    )
            elif resp.status_code == 200:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with dest_path.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                logger.info("Successfully downloaded file: %s", file_obj.filename)
                return
            else:
                resp.raise_for_status()
        raise RuntimeError("Too many redirects")
    except Exception as exc:
        # Exception text can embed the signed download URL — log type only.
        logger.warning(
            "Custom download failed (%s); falling back to standard file.download().",
            type(exc).__name__,
        )
        file_obj.download(str(dest_path))
