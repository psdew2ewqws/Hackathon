"""Anthropic SDK wrapper.

The SDK is imported lazily so the rest of the stack starts even when the
``anthropic`` extra is not installed. ``is_configured()`` reports both
conditions: the package must be importable AND ``ANTHROPIC_API_KEY`` must
be set.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

LOG = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024


class LLMNotConfiguredError(RuntimeError):
    """Raised when the chat path is invoked without an API key. Caller
    converts this to HTTP 503."""


def _import_anthropic() -> Any | None:
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError:
        return None
    return anthropic


class LLMClient:
    """Thin wrapper around ``anthropic.Anthropic``.

    Holds a single client instance per process. Reads model + max_tokens
    from environment at call time so a live deployment can switch model
    without a restart.
    """

    def __init__(self) -> None:
        self._anthropic: Any | None = None
        self._client: Any | None = None
        self._lock = threading.Lock()

    @staticmethod
    def model() -> str:
        return os.environ.get("TRAFFIC_INTEL_LLM_MODEL", DEFAULT_MODEL)

    @staticmethod
    def max_tokens() -> int:
        try:
            return int(os.environ.get("TRAFFIC_INTEL_LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS))
        except ValueError:
            return DEFAULT_MAX_TOKENS

    @staticmethod
    def has_api_key() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

    def is_configured(self) -> bool:
        if not self.has_api_key():
            return False
        if self._anthropic is None:
            self._anthropic = _import_anthropic()
        return self._anthropic is not None

    def get_async(self) -> Any:
        """Return a configured ``anthropic.AsyncAnthropic`` client.

        Raises LLMNotConfiguredError if the SDK or the API key is missing.
        Caller is expected to drive ``messages.stream()`` from an async context.
        """
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            if self._anthropic is None:
                self._anthropic = _import_anthropic()
            if self._anthropic is None:
                raise LLMNotConfiguredError(
                    "anthropic SDK not installed. Install with: pip install 'traffic-intel[llm]'"
                )
            if not self.has_api_key():
                raise LLMNotConfiguredError(
                    "ANTHROPIC_API_KEY is not set. The LLM advisor is opt-in — see "
                    "phase3-fullstack/docs/security_and_isolation.md#llm-advisor."
                )
            self._client = self._anthropic.AsyncAnthropic()
            LOG.info("Anthropic async client initialized (model=%s, max_tokens=%s)",
                     self.model(), self.max_tokens())
            return self._client

    def status(self) -> dict[str, Any]:
        """Public-facing summary for the /api/llm/status endpoint."""
        sdk_installed = _import_anthropic() is not None
        key_set = self.has_api_key()
        return {
            "configured": sdk_installed and key_set,
            "sdk_installed": sdk_installed,
            "api_key_set": key_set,
            "model": self.model(),
            "max_tokens": self.max_tokens(),
            "role_required": "operator",
            "egress": "api.anthropic.com" if (sdk_installed and key_set) else None,
        }


_shared: LLMClient | None = None
_shared_lock = threading.Lock()


def get_client() -> LLMClient:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = LLMClient()
        return _shared
