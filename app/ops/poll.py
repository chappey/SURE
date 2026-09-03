"""Background poll of OpenRouter account health."""

from __future__ import annotations

import asyncio
import logging

from app import config
from app.ops import health

logger = logging.getLogger(__name__)


async def poll_forever() -> None:
    interval = max(0, int(config.OPS_HEALTH_POLL_SECONDS))
    if interval <= 0:
        logger.info("OpenRouter health poll disabled (OPS_HEALTH_POLL_SECONDS=0)")
        return
    # First snapshot shortly after boot so the dashboard is not empty.
    await asyncio.sleep(2)
    while True:
        try:
            await asyncio.to_thread(health.refresh_openrouter_account)
        except Exception:
            logger.exception("OpenRouter account poll failed")
        await asyncio.sleep(interval)
