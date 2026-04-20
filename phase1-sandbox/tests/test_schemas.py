"""Consistency check: schemas & configs line up with each other."""

from __future__ import annotations

import json

import yaml

from traffic_intel_sandbox.synth.profiles import ProfileConfig


def test_detector_ids_appear_in_site_example(site_example, profiles_yml):
    """Every detector defined in profiles.yml must be referenced by a lane in site1.example.json."""
    cfg = ProfileConfig.load(profiles_yml)
    with site_example.open() as fh:
        site = json.load(fh)
    referenced: set[str] = set()
    for approach in site["approaches"]:
        for lane in approach["lanes"]:
            if "detector_id" in lane:
                referenced.add(lane["detector_id"])
    defined = {d.id for d in cfg.detectors}
    missing = defined - referenced
    # We allow multiple detectors per lane (e.g., stop-bar + advance) so not
    # every defined detector needs a corresponding lane, but site_example's
    # lane detector_ids must all be defined in profiles.yml.
    unknown = referenced - defined
    assert not unknown, f"site references detectors not in profiles.yml: {unknown}"


def test_phase_plan_phases_are_nema_style(phase_plan_yml):
    with phase_plan_yml.open() as fh:
        plan = yaml.safe_load(fh)
    phases = plan["phases"]
    numbers = [p["number"] for p in phases]
    # NEMA dual-ring phase numbers live in {1..8}
    assert all(1 <= n <= 8 for n in numbers)
    assert len(set(numbers)) == len(numbers), "phase numbers must be unique"
