"""Measure automated counts against a hand-labeled ground-truth window.

Reads a JSON file of human-labeled crossings (`{video_ts, approach, class}`)
and the matching window of `data/counts.ndjson`, then prints per-approach
MAE and per-class recall. The harness is the credibility hook the
production-readiness plan calls out — until counts have been compared to
a human label set, the system can claim accuracy only by assertion.

Usage:
    python phase3-fullstack/scripts/measure_counts.py \\
        --gt phase3-fullstack/data/measurement/gt_5min.json \\
        --counts phase3-fullstack/data/counts.ndjson \\
        --window 300

Both files are required. The window is the labeled span in seconds; the
script aligns the latest `window` seconds of counts.ndjson against the GT
crossings.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_gt(path: Path) -> tuple[list[dict], int]:
    data = json.loads(path.read_text())
    crossings = data.get("crossings") or []
    window = int(data.get("window_seconds") or 300)
    return crossings, window


def gt_aggregates(crossings: list[dict]) -> tuple[Counter, Counter]:
    """Count GT crossings per approach and per class."""
    per_approach: Counter = Counter()
    per_class: Counter = Counter()
    for c in crossings:
        per_approach[c["approach"]] += 1
        per_class[c.get("class", "car").lower()] += 1
    return per_approach, per_class


def load_recent_bins(path: Path, window_s: int) -> list[dict]:
    """Read counts.ndjson and return the bins covering the last `window_s` of wall time."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open() as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return []
    rows.sort(key=lambda r: r.get("bin_end", 0.0))
    last_ts = rows[-1].get("bin_end", 0.0)
    cutoff = last_ts - window_s
    return [r for r in rows if r.get("bin_end", 0.0) >= cutoff]


def auto_aggregates(bins: list[dict]) -> tuple[Counter, Counter]:
    """Sum crossings per approach + reconstruct per-class mix from `mix` field
    (mix is a snapshot of in-zone class counts, not crossings — but it gives
    us a class-recall proxy when no per-class crossing field exists)."""
    per_approach: Counter = Counter()
    per_class: Counter = Counter()
    for b in bins:
        for ap, n in (b.get("crossings_in_bin") or {}).items():
            per_approach[ap] += int(n)
        for ap_mix in (b.get("mix") or {}).values():
            for cls, n in (ap_mix or {}).items():
                per_class[cls.lower()] += int(n)
    return per_approach, per_class


def fmt_table(rows: list[tuple[str, ...]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for r in rows:
        out.append("  ".join(c.ljust(w) for c, w in zip(r, widths)))
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--gt", type=Path,
                   default=REPO_ROOT / "phase3-fullstack" / "data" / "measurement" / "gt_5min.json")
    p.add_argument("--counts", type=Path,
                   default=REPO_ROOT / "phase3-fullstack" / "data" / "counts.ndjson")
    p.add_argument("--window", type=int, default=None,
                   help="seconds; defaults to the GT file's window_seconds")
    args = p.parse_args()

    if not args.gt.exists():
        print(f"GT file not found: {args.gt}", file=sys.stderr)
        print("Tip: copy phase3-fullstack/data/measurement/gt_5min.example.json", file=sys.stderr)
        return 2

    gt_crossings, gt_window = load_gt(args.gt)
    window_s = args.window or gt_window
    gt_per_approach, gt_per_class = gt_aggregates(gt_crossings)

    bins = load_recent_bins(args.counts, window_s)
    auto_per_approach, auto_per_class = auto_aggregates(bins)

    print(f"GT file:        {args.gt}")
    print(f"Counts file:    {args.counts}  ({len(bins)} bins in last {window_s}s)")
    print(f"GT total:       {sum(gt_per_approach.values())} crossings")
    print(f"Auto total:     {sum(auto_per_approach.values())} crossings")
    print()

    # Per-approach MAE
    approaches = sorted(set(gt_per_approach) | set(auto_per_approach))
    rows = [("approach", "gt", "auto", "abs_err")]
    abs_errs = []
    for ap in approaches:
        gt_n = gt_per_approach.get(ap, 0)
        au_n = auto_per_approach.get(ap, 0)
        err = abs(gt_n - au_n)
        abs_errs.append(err)
        rows.append((ap, str(gt_n), str(au_n), str(err)))
    print("Per-approach crossings:")
    print(fmt_table(rows))
    if abs_errs:
        print(f"\nMAE per-approach: {sum(abs_errs)/len(abs_errs):.2f}")

    # Per-class recall (using auto's mix field as a coarse class signal)
    print()
    rows = [("class", "gt", "auto_seen", "recall")]
    for cls in sorted(set(gt_per_class) | set(auto_per_class)):
        gt_n = gt_per_class.get(cls, 0)
        au_n = auto_per_class.get(cls, 0)
        # "recall" here is "did we see ANY of this class when GT had it" — coarse;
        # a finer measure would require per-class crossings, future work.
        recall = "1.00" if (gt_n == 0 or au_n > 0) else "0.00"
        rows.append((cls, str(gt_n), str(au_n), recall))
    print("Per-class presence:")
    print(fmt_table(rows))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
