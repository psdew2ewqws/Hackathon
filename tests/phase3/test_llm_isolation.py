"""Confirms the LLM advisor is OFF by default and the §7.7 isolation
script keeps passing after the package was added.

These are the tests a judge can run to verify "no key set ⇒ no calls"
without trusting the dashboard text.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from traffic_intel_phase3.poc_wadi_saqra.llm.client import LLMClient


REPO_ROOT = Path(__file__).resolve().parents[2]
ISOLATION_SCRIPT = REPO_ROOT / "phase3-fullstack" / "scripts" / "assert_no_outbound_writes.sh"


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    """Force-clear ANTHROPIC_API_KEY for every test in this module so the
    'opt-in' default posture is exercised, regardless of how pytest was
    invoked."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


def test_no_outbound_writes_after_llm_added():
    """The bash isolation script must still PASS — the LLM package only
    uses the Anthropic SDK's high-level abstractions, never raw httpx/
    requests POSTs that would trip the regex set."""
    assert ISOLATION_SCRIPT.is_file()
    proc = subprocess.run(
        ["bash", str(ISOLATION_SCRIPT)],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, (
        f"isolation script regressed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "PASS" in proc.stdout


def test_status_reports_not_configured_without_key():
    s = LLMClient().status()
    assert s["configured"] is False
    assert s["api_key_set"] is False
    assert s["egress"] is None


def test_no_anthropic_module_initialised_at_import_time():
    """Importing the package must not eagerly instantiate the SDK or
    consume any environment variable."""
    import sys
    import importlib

    for k in list(sys.modules):
        if k.startswith("anthropic") and "anthropic_test" not in k:
            sys.modules.pop(k, None)

    from traffic_intel_phase3.poc_wadi_saqra import llm  # noqa: F401
    importlib.reload(llm)

    # The SDK may or may not be installed in this venv; what matters is
    # that no module-level call to anthropic.Anthropic() / AsyncAnthropic()
    # happened. ``client._shared`` is the singleton — should still be None
    # until ``get_client()`` is invoked.
    from traffic_intel_phase3.poc_wadi_saqra.llm import client as _client_mod
    assert _client_mod._shared is None  # noqa: SLF001


def test_no_anthropic_object_created_when_key_absent():
    """Even after asking for the client, no AsyncAnthropic instance should
    be constructed when the key is unset."""
    client = LLMClient()
    assert client.is_configured() is False
    # Internal cache should remain unset.
    assert client._client is None  # noqa: SLF001
