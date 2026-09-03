"""SQLite ledger of every LLM provider call (success and failure)."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from app import config

_lock = threading.Lock()
_local = threading.local()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    request_id TEXT,
    user_id TEXT,
    user_name TEXT,
    course_id TEXT,
    purpose TEXT,
    provider TEXT,
    model_id TEXT,
    model TEXT,
    mode TEXT,
    success INTEGER NOT NULL,
    error TEXT,
    latency_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost_usd REAL,
    prompt_chars INTEGER,
    generation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
CREATE INDEX IF NOT EXISTS idx_llm_calls_user_ts ON llm_calls(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model_ts ON llm_calls(model_id, ts);

CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alert_events_ts ON alert_events(ts);
"""


def db_path() -> Path:
    return Path(config.CACHE_DIR) / "ops" / "usage.db"


def _connect() -> sqlite3.Connection:
    path = db_path()
    cached_path = getattr(_local, "path", None)
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is not None and cached_path == str(path):
        return conn
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    _local.path = str(path)
    _local.conn = conn
    return conn


def init() -> None:
    with _lock:
        _connect()


def record_call(**fields: Any) -> None:
    row = {
        "ts": fields.get("ts", time.time()),
        "request_id": fields.get("request_id") or "",
        "user_id": fields.get("user_id") or "",
        "user_name": fields.get("user_name") or "",
        "course_id": fields.get("course_id") or "",
        "purpose": fields.get("purpose") or "",
        "provider": fields.get("provider") or "",
        "model_id": fields.get("model_id") or "",
        "model": fields.get("model") or "",
        "mode": fields.get("mode") or "",
        "success": 1 if fields.get("success") else 0,
        "error": (fields.get("error") or "")[:500],
        "latency_ms": fields.get("latency_ms"),
        "prompt_tokens": fields.get("prompt_tokens"),
        "completion_tokens": fields.get("completion_tokens"),
        "total_tokens": fields.get("total_tokens"),
        "cost_usd": fields.get("cost_usd"),
        "prompt_chars": fields.get("prompt_chars"),
        "generation_id": fields.get("generation_id") or "",
    }
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO llm_calls (
                ts, request_id, user_id, user_name, course_id, purpose,
                provider, model_id, model, mode, success, error, latency_ms,
                prompt_tokens, completion_tokens, total_tokens, cost_usd,
                prompt_chars, generation_id
            ) VALUES (
                :ts, :request_id, :user_id, :user_name, :course_id, :purpose,
                :provider, :model_id, :model, :mode, :success, :error, :latency_ms,
                :prompt_tokens, :completion_tokens, :total_tokens, :cost_usd,
                :prompt_chars, :generation_id
            )
            """,
            row,
        )
        conn.commit()


def record_alert(kind: str, severity: str, message: str, delivered: bool) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO alert_events (ts, kind, severity, message, delivered)
            VALUES (?, ?, ?, ?, ?)
            """,
            (time.time(), kind, severity, message[:1000], 1 if delivered else 0),
        )
        conn.commit()


def _since_clause(user_id: str | None, since_ts: float) -> tuple[str, list[Any]]:
    sql = "ts >= ?"
    args: list[Any] = [since_ts]
    if user_id is not None:
        sql += " AND user_id = ?"
        args.append(user_id)
    return sql, args


def spend_since(since_ts: float, user_id: str | None = None) -> float:
    where, args = _since_clause(user_id, since_ts)
    with _lock:
        conn = _connect()
        row = conn.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0) AS total FROM llm_calls WHERE {where}",
            args,
        ).fetchone()
    return float(row["total"] if row else 0)


def calls_since(since_ts: float, user_id: str | None = None) -> int:
    where, args = _since_clause(user_id, since_ts)
    with _lock:
        conn = _connect()
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM llm_calls WHERE {where}",
            args,
        ).fetchone()
    return int(row["n"] if row else 0)


def _rows(sql: str, args: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def summary_since(since_ts: float) -> dict[str, Any]:
    rows = _rows(
        """
        SELECT
            COUNT(*) AS calls,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successes,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failures,
            COALESCE(SUM(cost_usd), 0) AS spend_usd,
            COALESCE(SUM(total_tokens), 0) AS tokens
        FROM llm_calls
        WHERE ts >= ?
        """,
        (since_ts,),
    )
    row = rows[0] if rows else {}
    return {
        "calls": int(row.get("calls") or 0),
        "successes": int(row.get("successes") or 0),
        "failures": int(row.get("failures") or 0),
        "spend_usd": float(row.get("spend_usd") or 0),
        "tokens": int(row.get("tokens") or 0),
    }


def spend_by_user(since_ts: float, limit: int = 50) -> list[dict[str, Any]]:
    return _rows(
        """
        SELECT
            user_id,
            MAX(user_name) AS user_name,
            COUNT(*) AS calls,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failures,
            COALESCE(SUM(cost_usd), 0) AS spend_usd,
            COALESCE(SUM(total_tokens), 0) AS tokens
        FROM llm_calls
        WHERE ts >= ?
        GROUP BY user_id
        ORDER BY spend_usd DESC, calls DESC
        LIMIT ?
        """,
        (since_ts, limit),
    )


def spend_by_model(since_ts: float) -> list[dict[str, Any]]:
    return _rows(
        """
        SELECT
            model_id,
            MAX(model) AS model,
            MAX(provider) AS provider,
            COUNT(*) AS calls,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successes,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failures,
            COALESCE(SUM(cost_usd), 0) AS spend_usd,
            COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
        FROM llm_calls
        WHERE ts >= ?
        GROUP BY model_id
        ORDER BY calls DESC
        """,
        (since_ts,),
    )


def recent_calls(limit: int = 80) -> list[dict[str, Any]]:
    return _rows(
        """
        SELECT id, ts, request_id, user_id, user_name, course_id, purpose,
               provider, model_id, model, mode, success, error, latency_ms,
               prompt_tokens, completion_tokens, total_tokens, cost_usd,
               prompt_chars, generation_id
        FROM llm_calls
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )


def recent_alerts(limit: int = 40) -> list[dict[str, Any]]:
    return _rows(
        """
        SELECT id, ts, kind, severity, message, delivered
        FROM alert_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )


def spend_by_hour(since_ts: float) -> list[dict[str, Any]]:
    return _rows(
        """
        SELECT CAST(ts / 3600 AS INTEGER) * 3600 AS hour_ts,
               COUNT(*) AS calls,
               COALESCE(SUM(cost_usd), 0) AS spend_usd
        FROM llm_calls
        WHERE ts >= ?
        GROUP BY hour_ts
        ORDER BY hour_ts
        """,
        (since_ts,),
    )
