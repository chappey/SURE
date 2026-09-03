"""Per-user and global daily spend / call caps for paid LLM usage."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app import config
from app.exceptions import AppError
from app.ops import alerts, ledger

logger = logging.getLogger(__name__)


class BudgetExceeded(AppError):
    def __init__(self, detail: str, *, log_msg: str = ""):
        super().__init__(
            detail,
            status_code=429,
            log_msg=log_msg or detail,
            log_level=logging.WARNING,
        )


def utc_day_start(now: float | None = None) -> float:
    dt = datetime.fromtimestamp(now or datetime.now(timezone.utc).timestamp(), tz=timezone.utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).timestamp()


def _limits() -> dict[str, float | int]:
    return {
        "user_spend": float(config.USER_DAILY_SPEND_USD),
        "global_spend": float(config.GLOBAL_DAILY_SPEND_USD),
        "user_calls": int(config.USER_DAILY_LLM_CALLS),
        "global_calls": int(config.GLOBAL_DAILY_LLM_CALLS),
        "warn_ratio": float(config.BUDGET_WARN_RATIO),
    }


def snapshot(user_id: str | None = None) -> dict[str, float | int | str]:
    start = utc_day_start()
    limits = _limits()
    uid = (user_id or "").strip()
    user_spend = ledger.spend_since(start, uid) if uid else 0.0
    user_calls = ledger.calls_since(start, uid) if uid else 0
    return {
        "day_start_ts": start,
        "user_id": uid,
        "user_spend_usd": user_spend,
        "user_calls": user_calls,
        "global_spend_usd": ledger.spend_since(start),
        "global_calls": ledger.calls_since(start),
        "user_spend_limit_usd": limits["user_spend"],
        "global_spend_limit_usd": limits["global_spend"],
        "user_call_limit": limits["user_calls"],
        "global_call_limit": limits["global_calls"],
    }


def _maybe_warn(kind: str, used: float, limit: float, label: str) -> None:
    if limit <= 0:
        return
    ratio = used / limit
    warn_at = float(config.BUDGET_WARN_RATIO)
    if ratio >= 1.0:
        alerts.notify(
            kind=f"budget_exhausted:{kind}",
            severity="critical",
            message=f"{label} exhausted: {used:.4f} / {limit:.4f}. Further LLM calls are blocked.",
        )
    elif ratio >= warn_at:
        alerts.notify(
            kind=f"budget_warning:{kind}",
            severity="warning",
            message=f"{label} at {ratio:.0%} ({used:.4f} / {limit:.4f}).",
        )


def assert_within_budget(user_id: str | None = None) -> None:
    """Raise BudgetExceeded if this caller (or the app) is over today's caps."""
    limits = _limits()
    start = utc_day_start()
    uid = (user_id or "").strip()

    global_spend = ledger.spend_since(start)
    global_calls = ledger.calls_since(start)
    _maybe_warn("global_spend", global_spend, float(limits["global_spend"]), "Global daily spend")
    _maybe_warn("global_calls", float(global_calls), float(limits["global_calls"]), "Global daily LLM calls")

    if global_spend >= float(limits["global_spend"]) > 0:
        raise BudgetExceeded(
            f"Daily OpenRouter spend cap reached (${limits['global_spend']:.2f}). "
            "Try again tomorrow or ask an admin to raise GLOBAL_DAILY_SPEND_USD.",
            log_msg=f"global spend {global_spend:.4f} >= {limits['global_spend']}",
        )
    if global_calls >= int(limits["global_calls"]) > 0:
        raise BudgetExceeded(
            f"Daily LLM call cap reached ({limits['global_calls']} calls). Try again tomorrow.",
            log_msg=f"global calls {global_calls} >= {limits['global_calls']}",
        )

    if not uid:
        return

    user_spend = ledger.spend_since(start, uid)
    user_calls = ledger.calls_since(start, uid)
    _maybe_warn(
        f"user_spend:{uid}",
        user_spend,
        float(limits["user_spend"]),
        f"User {uid} daily spend",
    )
    _maybe_warn(
        f"user_calls:{uid}",
        float(user_calls),
        float(limits["user_calls"]),
        f"User {uid} daily LLM calls",
    )

    if user_spend >= float(limits["user_spend"]) > 0:
        raise BudgetExceeded(
            f"Your daily AI spend cap (${limits['user_spend']:.2f}) has been reached. "
            "Try again tomorrow or pick a cheaper model.",
            log_msg=f"user {uid} spend {user_spend:.4f} >= {limits['user_spend']}",
        )
    if user_calls >= int(limits["user_calls"]) > 0:
        raise BudgetExceeded(
            f"Your daily AI request cap ({limits['user_calls']} calls) has been reached. "
            "Try again tomorrow.",
            log_msg=f"user {uid} calls {user_calls} >= {limits['user_calls']}",
        )
