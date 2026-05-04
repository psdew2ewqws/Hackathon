"""Convert the gmaps typical-day ndjson into a clean JSON file for MCP.

Reads `data/research/gmaps/typical_2026-04-26.ndjson` (one row per
corridor x half-hour, 192 rows total) and emits
`data/research/gmaps/typical_2026-04-26.json` with the shape consumed
by the get_typical_day_gmaps MCP tool. Rows that the gmaps API failed
on (e.g. corridor S with HTTP 403) become a `null` entry — the MCP
tool surfaces them as missing rather than synthesising fake data.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "data" / "research" / "gmaps" / "typical_2026-04-26.ndjson"
DST = REPO_ROOT / "data" / "research" / "gmaps" / "typical_2026-04-26.json"

CORRIDORS = ("N", "S", "E", "W")
HALF_HOURS = [round(i * 0.5, 1) for i in range(48)]  # 0.0, 0.5, ..., 23.5


def _row(rec: dict) -> dict | None:
    if not rec.get("ok"):
        return None
    return {
        "congestion_ratio": rec.get("congestion_ratio"),
        "congestion_label": rec.get("congestion_label"),
        "speed_kmh": rec.get("speed_kmh"),
        "static_speed_kmh": rec.get("static_speed_kmh"),
        "duration_s": rec.get("duration_s"),
        "static_duration_s": rec.get("static_duration_s"),
    }


def _hour_key(local_hour: float) -> str:
    return f"{round(float(local_hour), 1):.1f}"


def main() -> int:
    grid: dict[str, dict[str, dict | None]] = {
        c: {_hour_key(h): None for h in HALF_HOURS} for c in CORRIDORS
    }
    captured_local: str | None = None
    with SRC.open() as fp:
        for line in fp:
            rec = json.loads(line)
            corridor = rec.get("corridor")
            if corridor not in grid:
                continue
            key = _hour_key(rec.get("local_hour", 0.0))
            if key not in grid[corridor]:
                continue
            grid[corridor][key] = _row(rec)
            if captured_local is None:
                captured_local = rec.get("departure_local", "")[:10] or None

    summary = {
        "peak_hour_per_corridor": {},
        "daily_avg_congestion_ratio": {},
    }
    for c in CORRIDORS:
        ratios = [
            (float(h), v["congestion_ratio"])
            for h, v in grid[c].items()
            if v and v.get("congestion_ratio") is not None
        ]
        if ratios:
            peak_h, _ = max(ratios, key=lambda t: t[1])
            avg = sum(r for _, r in ratios) / len(ratios)
            summary["peak_hour_per_corridor"][c] = round(peak_h, 1)
            summary["daily_avg_congestion_ratio"][c] = round(avg, 4)
        else:
            summary["peak_hour_per_corridor"][c] = None
            summary["daily_avg_congestion_ratio"][c] = None

    payload = {
        "site_id": "wadi_saqra",
        "captured": captured_local or "2026-04-26",
        "schema_version": 1,
        "source": "data/research/gmaps/typical_2026-04-26.ndjson",
        "corridors": grid,
        "summary": summary,
    }
    DST.write_text(json.dumps(payload, indent=2) + "\n")
    n_filled = sum(1 for c in CORRIDORS for v in grid[c].values() if v)
    print(f"wrote {DST}  ({n_filled} filled cells of {len(CORRIDORS) * 48})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
