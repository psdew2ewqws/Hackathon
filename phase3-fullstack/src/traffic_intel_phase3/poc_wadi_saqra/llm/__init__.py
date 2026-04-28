"""LLM advisor — opt-in conversational Q&A grounded in live Wadi Saqra data.

Activated by setting ``ANTHROPIC_API_KEY``. Without the key the dashboard
toggle still renders, but the chat endpoint returns 503 and no outbound
calls happen — preserving the §7.7 isolation default.
"""
from .client import LLMClient, LLMNotConfiguredError, get_client
from .runner import LLMContext, run_chat

__all__ = [
    "LLMClient",
    "LLMNotConfiguredError",
    "LLMContext",
    "get_client",
    "run_chat",
]
