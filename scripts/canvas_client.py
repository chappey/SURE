"""Shared Canvas API client for local SURE scripts."""

import os
import warnings

import config  # noqa: F401 — loads PROJECT_ROOT/.env


def get_canvas():
    """Return a configured Canvas client from CANVAS_API_URL and CANVAS_API_TOKEN."""
    from canvasapi import Canvas

    url = os.environ["CANVAS_API_URL"].rstrip("/")
    token = os.environ["CANVAS_API_TOKEN"]

    if url.startswith("http://") and (
        "localhost" in url or "127.0.0.1" in url
    ):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Canvas may respond unexpectedly",
                category=UserWarning,
            )
            return Canvas(url, token)

    return Canvas(url, token)
