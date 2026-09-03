"""Outbound operator alerts with per-kind cooldown. Generic webhook payload."""

from __future__ import annotations

import logging
import threading
import time

import requests

from app import config
from app.ops import ledger

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_last_sent: dict[str, float] = {}


def _webhook_url() -> str:
    return (config.ALERT_WEBHOOK_URL or "").strip()


def _min_interval() -> float:
    return float(config.ALERT_MIN_INTERVAL_SECONDS or 300)


def notify(*, kind: str, severity: str, message: str) -> None:
    """Record the event and POST to ALERT_WEBHOOK_URL unless silenced by cooldown."""
    now = time.time()
    with _lock:
        last = _last_sent.get(kind, 0.0)
        if now - last < _min_interval():
            return
        _last_sent[kind] = now

    delivered = False
    url = _webhook_url()
    if url:
        payload = {
            "text": message,
            "content": message,
            "message": message,
            "title": "EasyLearn",
            "severity": severity,
            "kind": kind,
        }
        try:
            requests.post(url, json=payload, timeout=8)
            delivered = True
        except Exception as exc:
            logger.warning("Alert webhook failed (%s): %s", kind, exc)
    else:
        logger.warning("ALERT [%s/%s] %s (no ALERT_WEBHOOK_URL configured)", severity, kind, message)

    try:
        ledger.record_alert(kind, severity, message, delivered)
    except Exception:
        logger.exception("Failed to persist alert event")

    if delivered:
        logger.warning("ALERT sent [%s/%s] %s", severity, kind, message)
