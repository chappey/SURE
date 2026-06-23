"""Shared Canvas API client."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

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
                "User-Agent": "EasyLearn/0.1.0 (LTI Quiz Generator; contact: admin@yourdomain.com)"
            }
        )

    return canvas


def download_canvas_file(canvas_client, file_obj, dest_path: str | Path, token: str | None = None) -> None:
    """Download a Canvas file, handling local Docker networking redirect loops."""
    dest_path = Path(dest_path)
    api_token = token or config.CANVAS_API_TOKEN
    headers: dict[str, str] = {}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    url = file_obj.url
    if "localhost:3000" in url or "canvas.docker:3000" in url or "127.0.0.1:3000" in url:
        headers["Host"] = "canvas.docker"

    try:
        session = requests.Session()
        current_url = url
        for i in range(10):
            req_headers = headers.copy() if i == 0 else {}
            if "Host" in headers:
                req_headers["Host"] = "canvas.docker"

            resp = session.get(current_url, headers=req_headers, allow_redirects=False, timeout=60)
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location")
                if not loc:
                    break
                current_url = (
                    loc.replace("://canvas.docker/", "://canvas.docker:3000/")
                    .replace("://canvas.docker:80/", "://canvas.docker:3000/")
                    .replace("://localhost/", "://localhost:3000/")
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
        logger.warning("Custom download failed: %s. Falling back to standard f.download().", exc)
        file_obj.download(str(dest_path))
