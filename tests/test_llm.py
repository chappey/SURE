from __future__ import annotations

import json
from unittest.mock import ANY, MagicMock, patch

import pytest

from app.llm.catalog import (
    _provider_configured,
    get_default_model_id,
    list_available_models,
    list_models_for_api,
    load_catalog as _load_catalog,
    resolve_auto_model,
    resolve_model,
)


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    _load_catalog.cache_clear()


def load_catalog():
    """Test helper that clears the LRU cache before loading."""
    _load_catalog.cache_clear()
    return _load_catalog()
from app.llm.errors import format_llm_error
from app.llm.fallback import (
    AllModelsFailedError,
    fallback_models,
    generate_json_with_fallback,
    generate_text_with_fallback,
)
from app.llm.schema_utils import prepare_openrouter_schema


#
# catalog
#
class TestProviderConfigured:
    def test_gemini_configured(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "abc")
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "abc")
        assert _provider_configured("gemini") is True

    def test_gemini_not_configured(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "")
        assert _provider_configured("gemini") is False

    def test_openrouter_configured(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "abc")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "abc")
        assert _provider_configured("openrouter") is True

    def test_unknown_provider(self):
        assert _provider_configured("unknown") is False  # type: ignore[arg-type]


class TestLoadCatalog:
    def test_loads_entries(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        entries = load_catalog()
        assert len(entries) == 3
        assert entries[0].id == "model-a"
        assert entries[0].provider == "gemini"

    def test_raises_on_missing_file(self, monkeypatch, tmp_path):
        missing = tmp_path / "does_not_exist.json"
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", missing)
        with pytest.raises(FileNotFoundError):
            load_catalog()

    def test_raises_on_empty_array(self, monkeypatch, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text("[]")
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", empty)
        with pytest.raises(ValueError, match="empty"):
            load_catalog()

    def test_result_is_cached(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        _load_catalog.cache_clear()
        first = _load_catalog()
        second = _load_catalog()
        assert first is second


class TestGetDefaultModelId:
    def test_returns_default_entry(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        assert get_default_model_id() == "model-a"

    def test_falls_back_to_first(self, monkeypatch, tmp_path):
        path = tmp_path / "no_default.json"
        path.write_text(json.dumps([
            {"id": "x", "label": "X", "provider": "gemini", "model": "x"},
        ]))
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", path)
        assert get_default_model_id() == "x"


class TestListAvailableModels:
    def test_filters_by_configured_providers(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "key")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "key")
        available = list_available_models()
        assert len(available) == 3

    def test_no_providers_configured(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "")
        assert list_available_models() == []


class TestResolveAutoModel:
    def test_picks_default(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "key")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "key")
        entry = resolve_auto_model()
        assert entry.id == "model-a"

    def test_raises_when_none_available(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "")
        with pytest.raises(ValueError, match="No AI provider"):
            resolve_auto_model()


class TestResolveModel:
    def test_none_falls_back_to_auto(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "key")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "key")
        entry = resolve_model(None)
        assert entry.id == "model-a"

    def test_explicit_valid_model(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "key")
        entry = resolve_model("model-b")
        assert entry.id == "model-b"

    def test_raises_for_unknown_model(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        with pytest.raises(ValueError, match="Unknown model"):
            resolve_model("nonexistent")

    def test_raises_when_provider_not_configured(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "")
        with pytest.raises(ValueError, match="not available"):
            resolve_model("model-a")


class TestListModelsForApi:
    def test_includes_all_models(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "key")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "key")
        result = list_models_for_api()
        assert len(result["models"]) == 3
        assert result["auto_model_id"] == "model-a"


#
# fallback
#
class TestFallbackModels:
    def test_all_available_when_no_request(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "key")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "key")
        models = fallback_models()
        assert len(models) == 3

    def test_primary_is_first_when_requested(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "key")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "key")
        models = fallback_models(requested_id="model-b")
        assert models[0].id == "model-b"
        assert len(models) == 3

    def test_raises_when_none_available(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.GEMINI_API_KEY", "")
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "")
        with pytest.raises(ValueError, match="No AI models"):
            fallback_models()

    def test_raises_when_requested_not_available(self, monkeypatch, ai_models_json):
        monkeypatch.setattr("app.llm.catalog.CATALOG_PATH", ai_models_json)
        monkeypatch.setattr("app.llm.catalog.config.OPENROUTER_API_KEY", "key")
        with pytest.raises(ValueError, match="not available"):
            fallback_models(requested_id="gemini-only")


class TestGenerateJsonWithFallback:
    def test_returns_first_success(self):
        model_a = MagicMock(id="a", provider="openrouter", model="a")

        def fake_generate_json(model, prompt, schema):
            if model.id == "a":
                return '{"ok": true}'
            raise RuntimeError("should not be called")

        with patch("app.llm.fallback._generate_json", side_effect=fake_generate_json):
            text, entry = generate_json_with_fallback([model_a], "prompt", {})
            assert text == '{"ok": true}'
            assert entry.id == "a"

    def test_falls_through_on_failure(self):
        def always_fails(model, prompt, schema):
            raise RuntimeError("fail")

        models = [
            MagicMock(id="m1", provider="openrouter", model="m1"),
            MagicMock(id="m2", provider="openrouter", model="m2"),
        ]
        with patch("app.llm.fallback._generate_json", side_effect=always_fails):
            with pytest.raises(AllModelsFailedError) as exc:
                generate_json_with_fallback(models, "prompt", {})
            assert len(exc.value.errors) == 2

    def test_returns_empty_string_triggers_fallback(self):
        def empty_on_first(model, prompt, schema):
            if model.id == "first":
                return ""
            return '{"ok": true}'

        models = [
            MagicMock(id="first", provider="openrouter", model="first"),
            MagicMock(id="second", provider="openrouter", model="second"),
        ]
        with patch("app.llm.fallback._generate_json", side_effect=empty_on_first):
            text, entry = generate_json_with_fallback(models, "prompt", {})
            assert text == '{"ok": true}'
            assert entry.id == "second"


class TestGenerateTextWithFallback:
    def test_returns_first_success(self):
        def fake_generate_text(model, prompt):
            if model.id == "a":
                return "hello"
            raise RuntimeError("should not be called")

        model_a = MagicMock(id="a", provider="gemini", model="a")
        with patch("app.llm.fallback._generate_text", side_effect=fake_generate_text):
            text, entry = generate_text_with_fallback([model_a], "prompt")
            assert text == "hello"
            assert entry.id == "a"

    def test_all_fail(self):
        models = [
            MagicMock(id="m1", provider="gemini", model="m1"),
        ]
        with patch("app.llm.fallback._generate_text", side_effect=RuntimeError("fail")):
            with pytest.raises(AllModelsFailedError):
                generate_text_with_fallback(models, "prompt")


class TestAllModelsFailedError:
    def test_user_message(self):
        err = AllModelsFailedError([("m1", "timeout"), ("m2", "quota")])
        assert "m1" in str(err)
        assert "m2" in str(err)
        assert "trying all available" in err.user_message


#
# schema_utils
#
class TestPrepareOpenrouterSchema:
    def test_sets_top_level_additional_properties_false(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = prepare_openrouter_schema(schema)
        assert result["additionalProperties"] is False

    def test_nested_objects_get_additional_properties_false(self):
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
                }
            },
        }
        result = prepare_openrouter_schema(schema)
        items_schema = result["properties"]["items"]["items"]
        assert items_schema["additionalProperties"] is False

    def test_does_not_mutate_original(self):
        original = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = prepare_openrouter_schema(original)
        result["extra"] = True
        assert "extra" not in original

    def test_defs_get_additional_properties(self):
        schema = {
            "type": "object",
            "$defs": {
                "Item": {"type": "object", "properties": {"id": {"type": "integer"}}}
            },
            "properties": {
                "items": {"type": "array", "items": {"$ref": "#/$defs/Item"}}
            },
        }
        result = prepare_openrouter_schema(schema)
        assert result["$defs"]["Item"].get("additionalProperties") is False


#
# errors
#
class TestFormatLlmError:
    def test_value_error(self):
        code, msg = format_llm_error(ValueError("bad input"))
        assert code == 400
        assert "bad input" in msg

    def test_runtime_error(self):
        model = MagicMock(label="TestModel")
        code, msg = format_llm_error(RuntimeError("boom"), model=model)
        assert code == 500
        assert "TestModel" in msg
        assert "boom" in msg

    def test_generic_exception(self):
        code, msg = format_llm_error(Exception("weird"))
        assert code == 500

    def test_all_models_failed_error(self):
        err = AllModelsFailedError([("m1", "fail")])
        code, msg = format_llm_error(err)
        assert code == 503
        assert "All models" not in msg
        assert "trying all available" in msg

    def test_gemini_429(self):
        from google.genai import errors as genai_errors
        exc = genai_errors.APIError(code=429, response_json={"error": {"message": "Rate limit"}})
        code, msg = format_llm_error(exc)
        assert code == 429

    def test_gemini_503(self):
        from google.genai import errors as genai_errors
        exc = genai_errors.APIError(code=503, response_json={"error": {"message": "Overloaded"}})
        code, msg = format_llm_error(exc)
        assert code == 503
        assert "temporarily unavailable" in msg
