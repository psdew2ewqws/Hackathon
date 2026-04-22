"""Fuse per-approach video counts with Google Maps corridor data, then
recommend traffic-light green-times via Webster's formula."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


CONGESTION_CLASSES = ("free", "light", "moderate", "heavy", "jam")


@dataclass(frozen=True)
class GmapsRow:
    corridor: str
    local_hour: float
    congestion_ratio: float
    congestion_label: str
    duration_s: float
    static_duration_s: float
    speed_kmh: float
    static_speed_kmh: float


def load_gmaps_all(path: Path) -> dict[str, dict[float, GmapsRow]]:
    """Index every ok row by corridor and half-hour bin."""
    out: dict[str, dict[float, GmapsRow]] = {}
    with Path(path).open() as fp:
        for line in fp:
            r = json.loads(line)
            if not r.get("ok"):
                continue
            corr = r.get("corridor")
            hr = float(r.get("local_hour", -1))
            out.setdefault(corr, {})[hr] = GmapsRow(
                corridor=corr,
                local_hour=hr,
                congestion_ratio=float(r.get("congestion_ratio") or 0.0),
                congestion_label=str(r.get("congestion_label") or "free"),
                duration_s=float(r.get("duration_s") or 0.0),
                static_duration_s=float(r.get("static_duration_s") or 0.0),
                speed_kmh=float(r.get("speed_kmh") or 0.0),
                static_speed_kmh=float(r.get("static_speed_kmh") or 0.0),
            )
    return out


def load_gmaps(path: Path, local_hour: float) -> dict[str, GmapsRow]:
    """Return the 4 corridor rows closest to local_hour."""
    all_rows = load_gmaps_all(path)
    out: dict[str, GmapsRow] = {}
    for corr, bins in all_rows.items():
        best_hr = min(bins.keys(), key=lambda h: abs(h - local_hour))
        out[corr] = bins[best_hr]
    return out


_LABEL_BOOST = {"free": 0.0, "light": 3.0, "moderate": 7.0, "heavy": 12.0, "jam": 20.0}


def gmaps_intensity(row: GmapsRow) -> float:
    """Map a gmaps row (ratio + label) to a standalone pressure score on the
    same scale as ``classify_pressure``. Meaningful even when live tracker
    pressure is zero. A ``jam`` row lands in the 'jam' bucket; a ``free`` row
    lands in 'free'."""
    ratio = float(row.congestion_ratio or 0.0)
    label = (row.congestion_label or "free").lower()
    # Base: 0 when ratio<=0.8 (free), grows with excess ratio. Gain 5 tuned so
    # ratio-only rows land in the bucket that matches their label (e.g. a heavy
    # row with ratio≈2.1 -> ~13 -> 'heavy'; a jam row with ratio≈2.4 -> ~20 -> 'jam').
    base = max(0.0, ratio - 0.8) * 5.0
    label_boost = _LABEL_BOOST.get(label, 0.0)
    # Labels dominate when present, otherwise base carries the signal.
    return max(base, label_boost * 0.6 + base)


def _live_multiplier(fused_now: dict[str, dict], approach: str) -> float:
    """Live tracker pressure augments the gmaps baseline but can't zero it out.
    Capped at 0.5 so gmaps remains the anchor."""
    live = float(fused_now.get(approach, {}).get("pressure", 0.0) or 0.0)
    return min(0.5, max(0.0, live / 25.0))


def forecast_per_approach(
    fused_now: dict[str, dict],
    gmaps_now: dict[str, GmapsRow],
    gmaps_target: dict[str, GmapsRow],
) -> dict[str, dict]:
    """
    Gmaps-anchored per-approach forecast:
        predicted_pressure(a) = gmaps_intensity(row_target_a) * (1 + live_mult(a))

    Live tracker pressure augments the gmaps baseline (capped at +50%) but
    never drives the prediction to zero when live is quiet.
    """
    out: dict[str, dict] = {}
    for approach in ("S", "N", "E", "W"):
        base = dict(fused_now.get(approach, {}))
        g_tgt = gmaps_target.get(approach)
        if not g_tgt:
            out[approach] = base
            continue
        intensity = gmaps_intensity(g_tgt)
        mult = _live_multiplier(fused_now, approach)
        predicted_pressure = intensity * (1.0 + mult)
        # Demand still scales with gmaps ratio movement when 'now' is available.
        g_now = gmaps_now.get(approach)
        if g_now and g_now.congestion_ratio > 0:
            demand_scale = g_tgt.congestion_ratio / g_now.congestion_ratio
        else:
            demand_scale = 1.0
        predicted_demand = float(base.get("demand_per_min", 0.0)) * demand_scale
        source = "live+gmaps" if mult > 0.1 else "gmaps"
        base.update({
            "gmaps_congestion_ratio": round(g_tgt.congestion_ratio, 3),
            "gmaps_ratio": round(g_tgt.congestion_ratio, 3),
            "gmaps_label": g_tgt.congestion_label,
            "gmaps_speed_kmh": round(g_tgt.speed_kmh, 1),
            "gmaps_intensity": round(intensity, 2),
            "live_multiplier": round(mult, 3),
            "scale_vs_now": round(demand_scale, 3),
            "pressure": round(predicted_pressure, 2),
            "demand_per_min": round(predicted_demand, 2),
            "label": classify_pressure(predicted_pressure),
            "source": source,
        })
        out[approach] = base
    return out


def build_heatmap(
    fused_now: dict[str, dict],
    all_rows: dict[str, dict[float, GmapsRow]],
    current_hour: float,
) -> dict:
    """
    Full 24h x 4-approach pressure grid at half-hour resolution.

    Returns:
      { "hours": [0.0, 0.5, ..., 23.5],
        "approaches": ["S","N","E","W"],
        "current_hour": 10.0,
        "cells": {
          "S": [{ "hour": 0.0, "pressure": ..., "label": ..., "gmaps_ratio": ..., "gmaps_label": ..., "gmaps_speed_kmh": ...}, ...],
          ...
        },
      }
    """
    hours_sorted = sorted({h for bins in all_rows.values() for h in bins.keys()})
    cells: dict[str, list[dict]] = {a: [] for a in ("S", "N", "E", "W")}
    for a in ("S", "N", "E", "W"):
        mult = _live_multiplier(fused_now, a)
        source = "live+gmaps" if mult > 0.1 else "gmaps"
        bins = all_rows.get(a, {})
        for h in hours_sorted:
            row = bins.get(h)
            if row is None:
                cells[a].append({
                    "hour": h, "pressure": None, "label": None,
                    "gmaps_ratio": None, "gmaps_label": None, "gmaps_speed_kmh": None,
                    "source": source,
                })
                continue
            intensity = gmaps_intensity(row)
            pressure = intensity * (1.0 + mult)
            cells[a].append({
                "hour": h,
                "pressure": round(pressure, 2),
                "label": classify_pressure(pressure),
                "gmaps_ratio": round(row.congestion_ratio, 3),
                "gmaps_label": row.congestion_label,
                "gmaps_speed_kmh": round(row.speed_kmh, 1),
                "gmaps_intensity": round(intensity, 2),
                "live_multiplier": round(mult, 3),
                "source": source,
            })
    return {
        "hours": hours_sorted,
        "approaches": ["S", "N", "E", "W"],
        "current_hour": current_hour,
        "cells": cells,
    }


def classify_pressure(pressure: float) -> str:
    """Map a continuous pressure score to the 5 gmaps classes."""
    if pressure < 2.0:   return "free"
    if pressure < 5.0:   return "light"
    if pressure < 9.0:   return "moderate"
    if pressure < 15.0:  return "heavy"
    return "jam"


def fuse(
    approach_counts: dict[str, dict[str, int]],
    bin_seconds: int,
    gmaps_rows: dict[str, GmapsRow],
) -> dict[str, dict]:
    """
    Input:
      approach_counts: { "N": {"in_zone": x, "crossings_in_bin": y, ...}, ... }
      bin_seconds:     duration of the most recent bin
      gmaps_rows:      per-corridor GmapsRow from load_gmaps

    Output per approach:
      {
        "in_zone", "crossings_in_bin",
        "demand_per_min", "queue",
        "gmaps_congestion_ratio", "gmaps_label",
        "pressure", "label"
      }
    """
    out: dict[str, dict] = {}
    for approach, c in approach_counts.items():
        in_zone = int(c.get("in_zone", 0))
        crossings = int(c.get("crossings_in_bin", 0))
        demand_per_min = (crossings * 60.0 / max(bin_seconds, 1))
        g = gmaps_rows.get(approach)
        ratio = g.congestion_ratio if g else 1.0
        penalty = max(0.0, ratio - 1.0) * 2.0
        # pressure = demand (veh/min) + 0.5 * queue * (1 + gmaps penalty)
        pressure = demand_per_min + 0.5 * in_zone * (1.0 + penalty)
        out[approach] = {
            "in_zone": in_zone,
            "crossings_in_bin": crossings,
            "demand_per_min": round(demand_per_min, 2),
            "queue": in_zone,
            "gmaps_congestion_ratio": round(ratio, 3) if g else None,
            "gmaps_label": g.congestion_label if g else None,
            "gmaps_speed_kmh": round(g.speed_kmh, 1) if g else None,
            "pressure": round(pressure, 2),
            "label": classify_pressure(pressure),
        }
    return out


def _phase_flow_ratio(fused: dict[str, dict], approaches: list[str], saturation: float) -> float:
    """Critical lane-group ratio for a phase = max(y_i) across its approaches."""
    ys = [min(0.95, max(0.02, fused.get(a, {}).get("pressure", 0.0) / saturation))
          for a in approaches]
    return max(ys) if ys else 0.02


def webster_two_phase(
    fused: dict[str, dict],
    current_plan: dict | None = None,
    saturation: float = 25.0,
    yellow_per_phase: float = 3.0,
    all_red_per_phase: float = 2.0,
    min_green: float = 10.0,
    max_green: float = 90.0,
) -> dict:
    """
    Webster for a 2-phase signal: NS (N+S open together) and EW (E+W together).
    Returns recommended cycle + NS/EW greens and a comparison vs ``current_plan``.

    ``current_plan`` example (matches the real Wadi Saqra signal):
        {"NS_green": 35, "EW_green": 35, "yellow": 3, "all_red": 2}
    """
    lost_per_phase = yellow_per_phase + all_red_per_phase  # ≈ 5s
    L = 2 * lost_per_phase

    y_NS = _phase_flow_ratio(fused, ["N", "S"], saturation)
    y_EW = _phase_flow_ratio(fused, ["E", "W"], saturation)
    Y = y_NS + y_EW

    if Y >= 0.95:
        cycle = 180.0
    else:
        cycle = (1.5 * L + 5.0) / (1.0 - Y)
    cycle = max(40.0, min(180.0, cycle))
    effective_green = cycle - L

    if Y > 0:
        g_NS = (y_NS / Y) * effective_green
        g_EW = (y_EW / Y) * effective_green
    else:
        g_NS = g_EW = effective_green / 2

    # clamp per-phase green
    g_NS = min(max_green, max(min_green, g_NS))
    g_EW = min(max_green, max(min_green, g_EW))
    cycle_recomputed = g_NS + g_EW + L

    # per-approach demand within each phase (for UI)
    per_phase_detail = {
        "NS": {
            "green_seconds": round(g_NS, 1),
            "flow_ratio": round(y_NS, 3),
            "approaches": {
                a: {
                    "pressure": fused.get(a, {}).get("pressure", 0.0),
                    "demand_per_min": fused.get(a, {}).get("demand_per_min", 0.0),
                    "in_zone": fused.get(a, {}).get("in_zone", 0),
                }
                for a in ("N", "S")
            },
        },
        "EW": {
            "green_seconds": round(g_EW, 1),
            "flow_ratio": round(y_EW, 3),
            "approaches": {
                a: {
                    "pressure": fused.get(a, {}).get("pressure", 0.0),
                    "demand_per_min": fused.get(a, {}).get("demand_per_min", 0.0),
                    "in_zone": fused.get(a, {}).get("in_zone", 0),
                }
                for a in ("E", "W")
            },
        },
    }

    out = {
        "mode": "two_phase",
        "cycle_seconds": round(cycle_recomputed, 1),
        "lost_time_seconds": round(L, 1),
        "flow_ratio_total": round(Y, 3),
        "phases": per_phase_detail,
        # Keep a flat per_approach view for continuity with the old UI.
        "per_approach": {
            a: {
                "green_seconds": round(g_NS if a in ("N", "S") else g_EW, 1),
                "flow_ratio": round(y_NS if a in ("N", "S") else y_EW, 3),
                "pressure": fused.get(a, {}).get("pressure", 0.0),
            }
            for a in ("N", "S", "E", "W")
        },
    }

    if current_plan:
        cur_NS = float(current_plan.get("NS_green", 35))
        cur_EW = float(current_plan.get("EW_green", 35))
        cur_yellow = float(current_plan.get("yellow", yellow_per_phase))
        cur_allred = float(current_plan.get("all_red", all_red_per_phase))
        cur_cycle = cur_NS + cur_EW + 2 * (cur_yellow + cur_allred)
        # Webster delay estimate (uniform term only, for relative comparison).
        def _delay(c, g_phase, y_phase):
            if y_phase <= 0 or g_phase <= 0:
                return 0.0
            r = 1 - g_phase / c                  # red ratio
            x = min(0.98, y_phase * c / g_phase) # degree of saturation
            # d = 0.5 * c * (1 - g/c)^2 / (1 - (g/c)*x)  — classic Webster uniform delay
            denom = max(1e-3, 1 - (g_phase / c) * x)
            return 0.5 * c * r * r / denom
        d_cur = _delay(cur_cycle, cur_NS, y_NS) + _delay(cur_cycle, cur_EW, y_EW)
        d_rec = _delay(cycle_recomputed, g_NS, y_NS) + _delay(cycle_recomputed, g_EW, y_EW)
        improvement = None
        if d_cur > 0:
            improvement = round(100.0 * (d_cur - d_rec) / d_cur, 1)
        out["comparison"] = {
            "current": {
                "NS_green": cur_NS,
                "EW_green": cur_EW,
                "yellow": cur_yellow,
                "all_red": cur_allred,
                "cycle_seconds": round(cur_cycle, 1),
                "uniform_delay_sec_per_veh": round(d_cur, 2),
            },
            "recommended": {
                "NS_green": round(g_NS, 1),
                "EW_green": round(g_EW, 1),
                "yellow": round(yellow_per_phase, 1),
                "all_red": round(all_red_per_phase, 1),
                "cycle_seconds": round(cycle_recomputed, 1),
                "uniform_delay_sec_per_veh": round(d_rec, 2),
            },
            "delay_reduction_pct": improvement,
        }

    return out


# Backwards-compat alias so existing callers keep working.
webster_recommendation = webster_two_phase
