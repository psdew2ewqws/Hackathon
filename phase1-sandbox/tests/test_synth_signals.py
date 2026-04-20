"""Synthetic signal log generator — format + cycle sanity checks."""

from __future__ import annotations

import json
from datetime import date, datetime

from traffic_intel_sandbox.synth.signal_logs import PhasePlan, generate


def _parse_lines(path):
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_ndjson_format(tmp_path, phase_plan_yml):
    written = generate(phase_plan_yml, tmp_path, days=1,
                       start_date=date(2026, 4, 7), intersection_id="T1", seed=1)
    events = _parse_lines(written[0])
    assert len(events) > 0
    for ev in events:
        assert set(ev.keys()) == {"timestamp", "intersection_id", "phase", "state"}
        assert ev["intersection_id"] == "T1"
        assert ev["state"] in {"GREEN_ON", "YELLOW_ON", "RED_ON"}
        # Round-trip parse timestamp
        datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))


def test_cycle_length_within_handbook_range(phase_plan_yml):
    plan = PhasePlan.load(phase_plan_yml)
    nominal = plan.nominal_cycle_s
    assert 90 <= nominal <= 120, f"nominal cycle {nominal}s outside handbook 90–120"


def test_states_alternate_green_yellow_red(tmp_path, phase_plan_yml):
    written = generate(phase_plan_yml, tmp_path, days=1,
                       start_date=date(2026, 4, 7), intersection_id="T1", seed=1)
    events = _parse_lines(written[0])
    # Within a single phase, expect GREEN → YELLOW → RED in order.
    for i in range(len(events) - 2):
        a, b, c = events[i], events[i + 1], events[i + 2]
        if a["phase"] == b["phase"] == c["phase"]:
            assert (a["state"], b["state"], c["state"]) == ("GREEN_ON", "YELLOW_ON", "RED_ON"), \
                f"bad sequence at idx {i}: {a['state']},{b['state']},{c['state']}"
