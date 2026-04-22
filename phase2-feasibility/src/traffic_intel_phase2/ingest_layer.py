"""Unified ingest service — Phase 2 §7.2.

Consumes the three source streams, validates every record against the JSON
schemas under ``data/schemas/``, and re-emits a single unified NDJSON so
downstream consumers can subscribe to *one* firehose instead of three:

    data/events/phase2.ndjson          — live YOLO incidents  (tail)
    data/signal_logs/signal_*.ndjson   — signal transitions   (tail newest day)
    data/detector_counts/*.parquet     — 15-min detector bins (poll latest mtime)

Outputs:

    data/ingest_unified.ndjson   — normalised union stream
    data/ingest_errors.ndjson    — validation failures (schema errors, unparseable lines)

Runs a **single pass** by default (``--once``) so it fits naturally into the
dashboard's poll cadence; passing ``--follow`` keeps it alive and drains
new lines as they arrive.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    from jsonschema import Draft202012Validator
    _HAVE_JSONSCHEMA = True
except Exception:     # noqa: BLE001 — soft dep, we still do shape checks
    Draft202012Validator = None  # type: ignore[assignment]
    _HAVE_JSONSCHEMA = False


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
SCHEMAS_DIR = DATA_DIR / "schemas"
UNIFIED_PATH = DATA_DIR / "ingest_unified.ndjson"
ERRORS_PATH = DATA_DIR / "ingest_errors.ndjson"


@dataclass
class Stats:
    detector_rows: int = 0
    signal_rows: int = 0
    incident_rows: int = 0
    errors: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "detector_rows": self.detector_rows,
            "signal_rows":   self.signal_rows,
            "incident_rows": self.incident_rows,
            "errors":        self.errors,
            "started_at":    self.started_at,
        }


def _load_validators() -> dict[str, Any]:
    """Returns a dict {source_kind → callable(record) → list[str] errors}.

    If jsonschema is not installed we fall back to a minimal required-fields
    check so the service still functions.
    """
    out: dict[str, Any] = {}
    schema_map = {
        "detector": SCHEMAS_DIR / "detector_count.schema.json",
        "signal":   SCHEMAS_DIR / "signal_event.schema.json",
        "incident": SCHEMAS_DIR / "incident_event.schema.json",
    }
    for kind, path in schema_map.items():
        if not path.exists():
            out[kind] = lambda rec, _k=kind: [f"schema file missing for {_k}"]
            continue
        schema = json.loads(path.read_text())
        if _HAVE_JSONSCHEMA:
            validator = Draft202012Validator(schema)
            def _check(rec: dict, _v=validator) -> list[str]:
                return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
                        for e in _v.iter_errors(rec)]
            out[kind] = _check
        else:
            required = schema.get("required", [])
            def _check(rec: dict, _r=required) -> list[str]:
                return [f"missing required: {k}" for k in _r if k not in rec]
            out[kind] = _check
    return out


# ── source readers ────────────────────────────────────────────────────────

def _iter_incidents(path: Path, offset: int = 0) -> Iterator[tuple[int, dict | None, str | None]]:
    """Yield (new_offset, record, raw_line_or_None_if_parse_error) from
    phase2.ndjson starting at byte ``offset``."""
    if not path.exists():
        return
    with path.open("rb") as fh:
        fh.seek(offset)
        for raw in fh:
            try:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                yield fh.tell(), json.loads(line), None
            except json.JSONDecodeError as exc:
                yield fh.tell(), None, f"json: {exc}"


def _iter_signal_latest(signal_dir: Path, offset: int = 0,
                         cursor_path: Path | None = None) -> Iterator[tuple[int, dict | None, str | None, Path]]:
    """Tail the newest signal_*.ndjson — returns (new_offset, record, err, file)."""
    files = sorted(signal_dir.glob("signal_*.ndjson"))
    if not files:
        return
    latest = files[-1]
    # Reset offset when the tailed file rotates
    if cursor_path is not None and cursor_path != latest:
        offset = 0
    with latest.open("rb") as fh:
        fh.seek(offset)
        for raw in fh:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            try:
                yield fh.tell(), json.loads(line), None, latest
            except json.JSONDecodeError as exc:
                yield fh.tell(), None, f"json: {exc}", latest


def _iter_detector_latest(counts_dir: Path, last_file: Path | None = None
                           ) -> Iterator[tuple[dict | None, str | None, Path]]:
    """Yield all rows from the newest counts_*.parquet if it is newer than
    ``last_file``. Returns (record, err, file)."""
    try:
        import pyarrow.parquet as pq  # noqa: WPS433
    except ImportError:
        return
    files = sorted(counts_dir.glob("counts_*.parquet"))
    if not files:
        return
    newest = files[-1]
    if last_file is not None and newest == last_file:
        return
    try:
        table = pq.read_table(newest)
    except Exception as exc:  # noqa: BLE001
        yield None, f"parquet read failed: {exc}", newest
        return
    for rec in table.to_pylist():
        # Normalise timestamp to ISO for NDJSON emission
        ts = rec.get("timestamp")
        if hasattr(ts, "isoformat"):
            rec["timestamp"] = ts.isoformat()
        yield rec, None, newest


# ── pipeline ──────────────────────────────────────────────────────────────

def _emit(fh_out, fh_err, source: str, record: dict | None,
          err: str | None, validators, stats: Stats) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    if err or record is None:
        fh_err.write(json.dumps({"ts": ts, "source": source,
                                 "error": err or "empty record"}) + "\n")
        stats.errors += 1
        return
    errs = validators[source](record)
    if errs:
        fh_err.write(json.dumps({"ts": ts, "source": source,
                                 "errors": errs, "record": record}) + "\n")
        stats.errors += 1
        return
    fh_out.write(json.dumps({"ingested_at": ts,
                              "source": source,
                              "record": record}) + "\n")
    if source == "detector":  stats.detector_rows += 1
    elif source == "signal":  stats.signal_rows += 1
    elif source == "incident": stats.incident_rows += 1


def run_once(counts_dir: Path, signals_dir: Path, events_path: Path,
             unified: Path = UNIFIED_PATH, errors: Path = ERRORS_PATH,
             state_path: Path | None = None) -> Stats:
    """Single drain pass. Advances cursors for each source so the next call
    only picks up new rows. Returns a Stats summary."""
    unified.parent.mkdir(parents=True, exist_ok=True)
    validators = _load_validators()
    state = _load_state(state_path) if state_path else {}
    stats = Stats()

    with unified.open("a") as fh_out, errors.open("a") as fh_err:
        # ── detector parquet (poll newest file)
        last_file_str = state.get("detector_last_file")
        last_file = Path(last_file_str) if last_file_str else None
        new_detector_file = last_file
        for rec, err, file_used in _iter_detector_latest(counts_dir, last_file):
            _emit(fh_out, fh_err, "detector", rec, err, validators, stats)
            new_detector_file = file_used
        state["detector_last_file"] = str(new_detector_file) if new_detector_file else None

        # ── signal NDJSON (tail newest day)
        sig_cursor = state.get("signal_cursor_file")
        sig_offset = int(state.get("signal_offset", 0) or 0)
        last_sig_file = None
        last_sig_offset = sig_offset
        for new_off, rec, err, file_used in _iter_signal_latest(
                signals_dir, sig_offset,
                Path(sig_cursor) if sig_cursor else None):
            _emit(fh_out, fh_err, "signal", rec, err, validators, stats)
            last_sig_file = file_used
            last_sig_offset = new_off
        if last_sig_file is not None:
            state["signal_cursor_file"] = str(last_sig_file)
            state["signal_offset"] = last_sig_offset

        # ── incident NDJSON (tail since offset)
        inc_offset = int(state.get("incident_offset", 0) or 0)
        last_inc_offset = inc_offset
        for new_off, rec, err in _iter_incidents(events_path, inc_offset):
            _emit(fh_out, fh_err, "incident", rec, err, validators, stats)
            last_inc_offset = new_off
        state["incident_offset"] = last_inc_offset

    if state_path:
        _save_state(state_path, state)
    return stats


def follow(counts_dir: Path, signals_dir: Path, events_path: Path,
           unified: Path = UNIFIED_PATH, errors: Path = ERRORS_PATH,
           state_path: Path | None = None,
           poll_interval_s: float = 1.0) -> None:
    """Long-running loop — run_once() with a sleep between passes. Prints a
    per-loop summary to stderr for observability."""
    while True:
        s = run_once(counts_dir, signals_dir, events_path, unified, errors, state_path)
        print(f"[ingest] detector={s.detector_rows} signal={s.signal_rows} "
              f"incident={s.incident_rows} errors={s.errors}", file=sys.stderr)
        time.sleep(poll_interval_s)


# ── state file ────────────────────────────────────────────────────────────

def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2))
    except OSError:
        pass


# ── CLI ───────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--counts-dir",  type=Path, default=DATA_DIR / "detector_counts")
    p.add_argument("--signals-dir", type=Path, default=DATA_DIR / "signal_logs")
    p.add_argument("--events",      type=Path, default=DATA_DIR / "events" / "phase2.ndjson")
    p.add_argument("--unified",     type=Path, default=UNIFIED_PATH)
    p.add_argument("--errors",      type=Path, default=ERRORS_PATH)
    p.add_argument("--state",       type=Path, default=DATA_DIR / "ingest_state.json")
    p.add_argument("--follow", action="store_true",
                   help="Run forever, draining new lines every --poll seconds")
    p.add_argument("--poll", type=float, default=1.0)
    p.add_argument("--reset", action="store_true",
                   help="Delete state + outputs before running")
    args = p.parse_args(argv)

    if args.reset:
        for path in (args.state, args.unified, args.errors):
            if path.exists():
                path.unlink()

    if args.follow:
        follow(args.counts_dir, args.signals_dir, args.events,
               args.unified, args.errors, args.state, args.poll)
        return 0
    s = run_once(args.counts_dir, args.signals_dir, args.events,
                 args.unified, args.errors, args.state)
    print(json.dumps(s.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
