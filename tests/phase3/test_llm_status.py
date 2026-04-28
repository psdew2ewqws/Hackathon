"""LLMClient status / is_configured behaviour."""
from __future__ import annotations

import os

import pytest

from traffic_intel_phase3.poc_wadi_saqra.llm.client import (
    LLMClient,
    LLMNotConfiguredError,
)


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TRAFFIC_INTEL_LLM_MODEL", raising=False)
    monkeypatch.delenv("TRAFFIC_INTEL_LLM_MAX_TOKENS", raising=False)
    yield


def test_default_status_no_key():
    client = LLMClient()
    s = client.status()
    assert s["configured"] is False
    assert s["api_key_set"] is False
    assert s["egress"] is None
    assert s["role_required"] == "operator"
    assert s["model"]  # still reports default model name


def test_is_configured_false_without_key():
    assert LLMClient().is_configured() is False


def test_get_async_raises_without_key():
    client = LLMClient()
    with pytest.raises(LLMNotConfiguredError):
        client.get_async()


def test_status_with_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    s = LLMClient().status()
    # If the SDK is not installed this stays False; we only assert the key flag.
    assert s["api_key_set"] is True


def test_model_env_override(monkeypatch):
    monkeypatch.setenv("TRAFFIC_INTEL_LLM_MODEL", "claude-opus-4-7")
    assert LLMClient.model() == "claude-opus-4-7"


def test_max_tokens_env_override(monkeypatch):
    monkeypatch.setenv("TRAFFIC_INTEL_LLM_MAX_TOKENS", "2048")
    assert LLMClient.max_tokens() == 2048


def test_max_tokens_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("TRAFFIC_INTEL_LLM_MAX_TOKENS", "not-a-number")
    assert LLMClient.max_tokens() > 0
