"""Assemble the operator dashboard payload."""

from __future__ import annotations

import time
from typing import Any

from app import config
from app.llm.catalog import load_catalog
from app.ops import budgets, health, ledger


def overview() -> dict[str, Any]:
    now = time.time()
    day = budgets.utc_day_start(now)
    week = now - 7 * 86400
    day_summary = ledger.summary_since(day)
    week_summary = ledger.summary_since(week)
    catalog = load_catalog()
    return {
        "generated_at": now,
        "today": day_summary,
        "week": week_summary,
        "budgets": budgets.snapshot(),
        "openrouter": health.provider_snapshot().get("openrouter") or {},
        "models": health.model_states(catalog),
        "spend_by_user": ledger.spend_by_user(day),
        "spend_by_model": ledger.spend_by_model(week),
        "spend_by_hour": ledger.spend_by_hour(week),
        "recent_calls": ledger.recent_calls(80),
        "recent_alerts": ledger.recent_alerts(40),
        "limits": {
            "generate_per_min": config.RATE_LIMIT_GENERATE_PER_MIN,
            "feedback_per_min": config.RATE_LIMIT_FEEDBACK_PER_MIN,
            "user_daily_spend_usd": config.USER_DAILY_SPEND_USD,
            "global_daily_spend_usd": config.GLOBAL_DAILY_SPEND_USD,
            "user_daily_llm_calls": config.USER_DAILY_LLM_CALLS,
            "global_daily_llm_calls": config.GLOBAL_DAILY_LLM_CALLS,
            "circuit_failures": config.MODEL_CIRCUIT_FAILURES,
            "circuit_open_seconds": config.MODEL_CIRCUIT_OPEN_SECONDS,
            "alert_webhook_configured": bool((config.ALERT_WEBHOOK_URL or "").strip()),
        },
    }
