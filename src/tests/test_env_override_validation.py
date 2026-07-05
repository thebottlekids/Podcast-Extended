"""
Tests for validation of env-var overrides applied to LLM configuration.

Guards against a real production incident: LLM_MODEL set without a litellm
provider prefix (e.g. "qwen2.5:14b" instead of "ollama/qwen2.5:14b") was
silently force-written into a working DB config on every env-var hash change,
breaking ad classification with no warning.
"""

from typing import Any

from app.config_store import (
    _apply_llm_model_override,
    _looks_like_llm_api_key,
    _looks_like_valid_llm_model,
)
from shared.config import Config, OutputConfig, ProcessingConfig


def _make_config(llm_model: str) -> Config:
    return Config(
        llm_api_key="test-key",
        llm_model=llm_model,
        output=OutputConfig(
            fade_ms=3000,
            min_ad_segement_separation_seconds=60,
            min_ad_segment_length_seconds=14,
            min_confidence=0.8,
        ),
        processing=ProcessingConfig(
            num_segments_to_input_to_prompt=30,
        ),
    )


class TestLooksLikeValidLlmModel:
    def test_rejects_model_without_provider_prefix(self) -> None:
        assert _looks_like_valid_llm_model("qwen2.5:14b") is False

    def test_rejects_empty_and_whitespace(self) -> None:
        assert _looks_like_valid_llm_model("") is False
        assert _looks_like_valid_llm_model("   ") is False
        assert _looks_like_valid_llm_model(None) is False

    def test_accepts_recognized_provider_prefixes(self) -> None:
        assert _looks_like_valid_llm_model("ollama/qwen2.5:14b") is True
        assert _looks_like_valid_llm_model("openai/gpt-4o") is True
        assert _looks_like_valid_llm_model("anthropic/claude-3-5-sonnet") is True
        assert _looks_like_valid_llm_model("groq/llama-3.1-70b") is True


class TestLooksLikeLlmApiKey:
    def test_rejects_value_that_looks_like_a_model_string(self) -> None:
        # This is the exact swapped-env-var mistake seen in production.
        assert _looks_like_llm_api_key("openai/qwen2.5:14b") is False

    def test_rejects_empty(self) -> None:
        assert _looks_like_llm_api_key("") is False
        assert _looks_like_llm_api_key(None) is False

    def test_accepts_plausible_api_key(self) -> None:
        assert _looks_like_llm_api_key("sk-abc123def456") is True
        assert _looks_like_llm_api_key("gsk_abc123def456") is True
        assert _looks_like_llm_api_key("not-needed") is True


class TestApplyLlmModelOverride:
    def test_unprefixed_env_model_does_not_overwrite_valid_db_value(
        self, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("LLM_MODEL", "qwen2.5:14b")
        cfg = _make_config(llm_model="ollama/qwen2.5:14b")

        _apply_llm_model_override(cfg)

        assert cfg.llm_model == "ollama/qwen2.5:14b"

    def test_prefixed_env_model_overrides_as_expected(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o")
        cfg = _make_config(llm_model="ollama/qwen2.5:14b")

        _apply_llm_model_override(cfg)

        assert cfg.llm_model == "openai/gpt-4o"

    def test_no_env_var_leaves_db_value_untouched(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("LLM_MODEL", raising=False)
        cfg = _make_config(llm_model="ollama/qwen2.5:14b")

        _apply_llm_model_override(cfg)

        assert cfg.llm_model == "ollama/qwen2.5:14b"
