"""Usage ledger, spend caps, per-user rate limits, circuits, ops auth."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.llm.catalog import ModelEntry
from app.ops import alerts, budgets, health, ledger
from app.ops.auth import tokens_match
from app.ops.trace import counts_as_outage, run_llm_call, usage_from_openai
from app.rate_limiter import InMemoryRateLimiter


@pytest.fixture(autouse=True)
def _reset_ops(monkeypatch):
    health.reset()
    monkeypatch.setattr(alerts, "_last_sent", {})
    monkeypatch.setattr(alerts, "_webhook_url", lambda: "")
    yield
    health.reset()


def _entry(model_id: str = "m1") -> ModelEntry:
    return ModelEntry(id=model_id, label=model_id, provider="openrouter", model="vendor/m")


class FakeRequest:
    def __init__(self, user_id: str | None):
        self.session = {}
        if user_id is not None:
            self.session["canvas_user_id"] = user_id
        self.client = SimpleNamespace(host="203.0.113.9")


class TestLedger:
    def test_records_spend_per_user(self):
        ledger.record_call(
            user_id="u1",
            success=True,
            cost_usd=0.25,
            total_tokens=100,
            model_id="m1",
            provider="openrouter",
        )
        ledger.record_call(
            user_id="u2",
            success=True,
            cost_usd=0.10,
            total_tokens=40,
            model_id="m1",
            provider="openrouter",
        )
        since = time.time() - 10
        assert ledger.spend_since(since, "u1") == pytest.approx(0.25)
        assert ledger.spend_since(since, "u2") == pytest.approx(0.10)
        assert ledger.spend_since(since) == pytest.approx(0.35)
        assert ledger.calls_since(since, "u1") == 1
        by_user = ledger.spend_by_user(since)
        assert by_user[0]["user_id"] == "u1"


class TestBudgets:
    def test_blocks_when_user_spend_cap_hit(self, monkeypatch):
        monkeypatch.setattr("app.config.USER_DAILY_SPEND_USD", 0.05)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_SPEND_USD", 100.0)
        monkeypatch.setattr("app.config.USER_DAILY_LLM_CALLS", 1000)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_LLM_CALLS", 1000)
        ledger.record_call(user_id="u1", success=True, cost_usd=0.06)
        with pytest.raises(budgets.BudgetExceeded, match="daily AI spend cap"):
            budgets.assert_within_budget("u1")

    def test_blocks_global_call_cap(self, monkeypatch):
        monkeypatch.setattr("app.config.USER_DAILY_SPEND_USD", 100.0)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_SPEND_USD", 100.0)
        monkeypatch.setattr("app.config.USER_DAILY_LLM_CALLS", 1000)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_LLM_CALLS", 1)
        ledger.record_call(user_id="u1", success=True, cost_usd=0.0)
        with pytest.raises(budgets.BudgetExceeded, match="Daily LLM call cap"):
            budgets.assert_within_budget("u1")

    def test_allows_under_cap(self, monkeypatch):
        monkeypatch.setattr("app.config.USER_DAILY_SPEND_USD", 5.0)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_SPEND_USD", 50.0)
        monkeypatch.setattr("app.config.USER_DAILY_LLM_CALLS", 100)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_LLM_CALLS", 1000)
        ledger.record_call(user_id="u1", success=True, cost_usd=0.01)
        budgets.assert_within_budget("u1")


class TestRateLimiter:
    def test_requires_canvas_user_id(self):
        limiter = InMemoryRateLimiter(max_requests=5, window_seconds=60)
        with pytest.raises(HTTPException) as exc:
            limiter.check(FakeRequest(None))
        assert exc.value.status_code == 401

    def test_buckets_are_per_user(self):
        limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)
        limiter.check(FakeRequest("alice"))
        limiter.check(FakeRequest("alice"))
        with pytest.raises(HTTPException) as exc:
            limiter.check(FakeRequest("alice"))
        assert exc.value.status_code == 429
        limiter.check(FakeRequest("bob"))


class TestCircuit:
    def test_opens_after_threshold(self, monkeypatch):
        monkeypatch.setattr("app.config.MODEL_CIRCUIT_FAILURES", 2)
        monkeypatch.setattr("app.config.MODEL_CIRCUIT_OPEN_SECONDS", 600)
        health.record_failure("m1", "503", counts=True)
        assert health.is_open("m1") is False
        health.record_failure("m1", "503", counts=True)
        assert health.is_open("m1") is True
        health.record_success("m1")
        assert health.is_open("m1") is False

    def test_schema_failures_do_not_count(self):
        health.record_failure("m1", "400 bad schema", counts=False)
        health.record_failure("m1", "400 bad schema", counts=False)
        health.record_failure("m1", "400 bad schema", counts=False)
        assert health.is_open("m1") is False

    def test_prefer_healthy_skips_open_when_alternative_exists(self, monkeypatch):
        monkeypatch.setattr("app.config.MODEL_CIRCUIT_FAILURES", 1)
        a = _entry("a")
        b = _entry("b")
        health.record_failure("a", "down")
        from app.ops.health import prefer_healthy

        assert [m.id for m in prefer_healthy([a, b])] == ["b"]


class TestTrace:
    def test_records_success_and_usage(self, monkeypatch):
        monkeypatch.setattr("app.config.USER_DAILY_SPEND_USD", 5.0)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_SPEND_USD", 50.0)
        monkeypatch.setattr("app.config.USER_DAILY_LLM_CALLS", 100)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_LLM_CALLS", 1000)

        class Resp:
            id = "gen_1"
            usage = SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cost=0.002,
                model_extra={},
            )

            def model_dump(self):
                return {
                    "id": "gen_1",
                    "model": "google/gemini-3.1-flash-lite",
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                        "cost": 0.002,
                    },
                }

        result = run_llm_call(
            _entry(),
            "json_schema",
            lambda: Resp(),
            prompt_chars=12,
            usage_from=usage_from_openai,
        )
        assert result.id == "gen_1"
        rows = ledger.recent_calls(1)
        assert rows[0]["success"] == 1
        assert rows[0]["cost_usd"] == pytest.approx(0.002)
        assert rows[0]["generation_id"] == "gen_1"
        assert rows[0]["model"] == "google/gemini-3.1-flash-lite"

    def test_usage_parse_failure_does_not_fail_call(self, monkeypatch):
        monkeypatch.setattr("app.config.USER_DAILY_SPEND_USD", 5.0)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_SPEND_USD", 50.0)
        monkeypatch.setattr("app.config.USER_DAILY_LLM_CALLS", 100)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_LLM_CALLS", 1000)

        class Resp:
            id = "gen_2"

        def boom(_):
            raise TypeError("'NoneType' object is not subscriptable")

        result = run_llm_call(_entry(), "json_schema", lambda: Resp(), usage_from=boom)
        assert result.id == "gen_2"
        rows = ledger.recent_calls(1)
        assert rows[0]["success"] == 1

    def test_records_failure_and_trips_outage(self, monkeypatch):
        monkeypatch.setattr("app.config.MODEL_CIRCUIT_FAILURES", 1)
        monkeypatch.setattr("app.config.USER_DAILY_SPEND_USD", 5.0)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_SPEND_USD", 50.0)
        monkeypatch.setattr("app.config.USER_DAILY_LLM_CALLS", 100)
        monkeypatch.setattr("app.config.GLOBAL_DAILY_LLM_CALLS", 1000)

        class Boom(Exception):
            status_code = 503

        with pytest.raises(Boom):
            run_llm_call(_entry("down-model"), "text", lambda: (_ for _ in ()).throw(Boom("unavailable")))
        assert health.is_open("down-model") is True
        rows = ledger.recent_calls(1)
        assert rows[0]["success"] == 0

    def test_counts_as_outage(self):
        assert counts_as_outage(SimpleNamespace(status_code=503))
        assert counts_as_outage(SimpleNamespace(status_code=429))
        assert not counts_as_outage(SimpleNamespace(status_code=400))
        assert counts_as_outage(TimeoutError("x"))


    def test_redacts_key_shaped_labels(self):
        from app.ops.health import _public_key_label

        assert _public_key_label("sk-or-v1-abc") == "API key"
        assert _public_key_label("EasyLearn prod") == "EasyLearn prod"
        assert _public_key_label("") == "API key"
    def test_tokens_match(self):
        assert tokens_match("secret-token", "secret-token")
        assert not tokens_match("nope", "secret-token")
        assert not tokens_match("", "secret-token")
        assert not tokens_match("secret-token", "")


class TestOpsRoutes:
    def test_ops_disabled_without_token(self, monkeypatch):
        monkeypatch.setattr("app.config.OPS_ADMIN_TOKEN", "")
        monkeypatch.setattr("app.config.OPS_HEALTH_POLL_SECONDS", 0)
        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app) as client:
            assert client.get("/ops").status_code == 404
            assert client.get("/ops/api/overview").status_code == 404

    def test_ops_overview_requires_token(self, monkeypatch):
        monkeypatch.setattr("app.config.OPS_ADMIN_TOKEN", "ops-secret-token")
        monkeypatch.setattr("app.config.OPS_HEALTH_POLL_SECONDS", 0)
        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app) as client:
            assert client.get("/ops/api/overview").status_code == 401
            ok = client.get(
                "/ops/api/overview",
                headers={"Authorization": "Bearer ops-secret-token"},
            )
            assert ok.status_code == 200
            body = ok.json()
            assert "today" in body
            assert "budgets" in body
            assert "models" in body
            assert "limits" in body
