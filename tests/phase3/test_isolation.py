"""§7.7 isolation assertion.

Shells out to the assertion script to confirm the source tree has no
outbound-write HTTP patterns. Any PR that regresses this fails CI.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def test_no_outbound_writes_in_source_tree():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "phase3-fullstack" / "scripts" / "assert_no_outbound_writes.sh"
    assert script.is_file(), f"missing isolation script at {script}"
    assert os.access(script, os.X_OK), "isolation script must be executable"
    proc = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"isolation script failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "PASS" in proc.stdout
