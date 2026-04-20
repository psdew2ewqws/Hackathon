"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = REPO_ROOT / "phase1-sandbox" / "configs"
METADATA = REPO_ROOT / "phase1-sandbox" / "src" / "traffic_intel_sandbox" / "metadata"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def profiles_yml() -> Path:
    return CONFIGS / "profiles.yml"


@pytest.fixture(scope="session")
def phase_plan_yml() -> Path:
    return CONFIGS / "phase_plan.yml"


@pytest.fixture(scope="session")
def intersection_schema() -> Path:
    return METADATA / "intersection_schema.json"


@pytest.fixture(scope="session")
def site_example() -> Path:
    return METADATA / "site1.example.json"
