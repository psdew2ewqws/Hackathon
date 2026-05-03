"""Drift checks for the production-readiness plan (Phase 2).

Production AI failures usually come from data drift, not algorithmic
weakness — the most-cited deployment-failure mode is "constant plan
switching" caused by silent input degradation. These four checks turn
common drift modes into ``drift_alert`` incidents through the existing
event engine, so the operator sees them in the same surface as wrong-way
and queue-spillback.

The checks are deliberately stateful (they remember what they last
warned about) so a long-running background job can call them every N
seconds without spamming the incidents table.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..poc_wadi_saqra.events import EventEngine
    from ..poc_wadi_saqra.tracker import TrackerService

LOG = logging.getLogger(__name__)


# ---------------- internal: alert-rate limiter ----------------

@dataclass
class _AlertGate:
    """Cooldown so a stuck-bad signal doesn't fire every poll."""
    cooldown_s: float = 300.0
    _last_fire: dict[str, float] = field(default_factory=dict)

    def should_fire(self, key: str, *, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        last = self._last_fire.get(key, 0.0)
        if now - last < self.cooldown_s:
            return False
        self._last_fire[key] = now
        return True


# ---------------- 4 individual checks ----------------

def check_detector_fps(
    tracker: "TrackerService", *, threshold: float = 2.0,
) -> tuple[bool, str]:
    """True if FPS is unhealthy. Returns (alert?, message)."""
    fps = float(getattr(tracker.state, "fps", 0.0) or 0.0)
    running = bool(getattr(tracker.state, "running", False))
    if not running:
        return True, "tracker is not running"
    if fps < threshold:
        return True, f"detector FPS {fps:.1f} < threshold {threshold}"
    return False, f"detector FPS {fps:.1f} OK"


def check_signal_log_freshness(
    path: Path, *, max_age_s: float = 300.0,
) -> tuple[bool, str]:
    if not path.exists():
        return True, f"signal log missing: {path}"
    age = time.time() - path.stat().st_mtime
    if age > max_age_s:
        return True, f"signal log stale ({age:.0f}s, max {max_age_s:.0f}s)"
    return False, f"signal log fresh ({age:.0f}s)"


def check_model_age(path: Path, *, max_age_days: float = 30.0) -> tuple[bool, str]:
    if not path.exists():
        return True, f"model missing: {path}"
    age_days = (time.time() - path.stat().st_mtime) / 86400.0
    if age_days > max_age_days:
        return True, f"model {path.name} is {age_days:.0f}d old (max {max_age_days:.0f}d)"
    return False, f"model {path.name} {age_days:.0f}d old"


def kl_divergence(p: dict[str, int], q: dict[str, int], *, eps: float = 1e-6) -> float:
    """Symmetric Kullback-Leibler between two count distributions."""
    keys = set(p) | set(q)
    if not keys:
        return 0.0
    total_p = sum(p.values()) or 1
    total_q = sum(q.values()) or 1
    pp = {k: max(p.get(k, 0) / total_p, eps) for k in keys}
    qq = {k: max(q.get(k, 0) / total_q, eps) for k in keys}
    kl_pq = sum(pp[k] * math.log(pp[k] / qq[k]) for k in keys)
    kl_qp = sum(qq[k] * math.log(qq[k] / pp[k]) for k in keys)
    return 0.5 * (kl_pq + kl_qp)


def check_class_mix_drift(
    baseline: dict[str, int],
    recent: dict[str, int],
    *,
    threshold_kl: float = 0.5,
) -> tuple[bool, str]:
    """Symmetric KL between baseline and recent class-mix histograms."""
    kl = kl_divergence(baseline, recent)
    if kl > threshold_kl:
        return True, f"class mix drifted: KL={kl:.2f} > {threshold_kl} (baseline={baseline} recent={recent})"
    return False, f"class mix steady: KL={kl:.2f}"


# ---------------- orchestrator ----------------

class DriftMonitor:
    """Run all four checks and emit incidents through the event engine."""

    def __init__(
        self,
        tracker: "TrackerService",
        events: "EventEngine",
        *,
        signal_log_path: Path,
        model_paths: list[Path],
        cooldown_s: float = 300.0,
    ) -> None:
        self.tracker = tracker
        self.events = events
        self.signal_log_path = signal_log_path
        self.model_paths = list(model_paths)
        self._gate = _AlertGate(cooldown_s=cooldown_s)

    def run_once(self, baseline_mix: dict[str, int] | None = None) -> dict:
        """Run all checks; return per-check {alert, message} regardless of
        whether the alert fired (rate-limit gates suppress repeats)."""
        results: dict[str, dict] = {}

        alert, msg = check_detector_fps(self.tracker)
        results["detector_fps"] = {"alert": alert, "message": msg}
        if alert and self._gate.should_fire("detector_fps"):
            self.events.emit_drift_alert("detector_fps", msg, severity="warning")

        alert, msg = check_signal_log_freshness(self.signal_log_path)
        results["signal_log"] = {"alert": alert, "message": msg}
        if alert and self._gate.should_fire("signal_log"):
            self.events.emit_drift_alert("signal_log", msg, severity="warning")

        for mp in self.model_paths:
            alert, msg = check_model_age(mp)
            key = f"model_age:{mp.name}"
            results[key] = {"alert": alert, "message": msg}
            if alert and self._gate.should_fire(key):
                self.events.emit_drift_alert("model_age", msg, severity="info")

        if baseline_mix is not None:
            recent = self._aggregate_recent_mix()
            alert, msg = check_class_mix_drift(baseline_mix, recent)
            results["class_mix"] = {"alert": alert, "message": msg}
            if alert and self._gate.should_fire("class_mix"):
                self.events.emit_drift_alert(
                    "class_mix", msg, severity="info",
                    payload_extra={"baseline": baseline_mix, "recent": recent},
                )
        return results

    def _aggregate_recent_mix(self) -> dict[str, int]:
        out: dict[str, int] = {}
        counts = (self.tracker.state.counts or {}) if self.tracker else {}
        for approach in counts.values():
            for cls, n in (approach.get("mix") or {}).items():
                out[cls] = out.get(cls, 0) + int(n)
        return out
