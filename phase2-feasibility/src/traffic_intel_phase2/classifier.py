"""Rule-based event classifier for Phase 1 §6.6 ground-truth closure.

Consumes the per-clip ndjson emitted by ``detect_track.py`` and assigns each
clip one tag from the Phase 1 taxonomy (see ``taxonomy.yml``). Two passes:

    Pass A  — pure aggregation over the ndjson (fast, interpretable).
    Pass B  — optional re-sampling of the normalized video to catch classes
              the ndjson does not reveal (stalled_vehicle, abnormal_stop,
              pedestrian_interaction). Runs only when Pass A returns
              ``insufficient_evidence`` and a normalized clip is on disk.

All tunable numbers live in ``phase2-feasibility/configs/classifier_thresholds.yml``.

CLI
---
Single clip::
    phase2-classify data/events/per-clip/site1_wrongway_01.ndjson

Batch update the manifest::
    phase2-classify --batch --update-manifest

Run Pass B on ambiguous clips::
    phase2-classify --batch --update-manifest --normalized-dir data/normalized/events
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_THRESHOLDS = REPO_ROOT / "phase2-feasibility/configs/classifier_thresholds.yml"
DEFAULT_MANIFEST = REPO_ROOT / "data/labels/clips_manifest.json"
DEFAULT_EVENTS_DIR = REPO_ROOT / "data/events/per-clip"
DEFAULT_METADATA = REPO_ROOT / "phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json"

# Order matters: first matched wins in Pass A. The rule set goes from
# most-specific positive to general.
PASS_A_ORDER = (
    "gridlock",
    "queue_spillback",
    "sudden_congestion",
    "unexpected_trajectory",
    "normal",
)


# ────────────────────────────────────────────────────────────────────────────
# Result types
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class ClipFeatures:
    """Aggregated primitives extracted from a clip's ndjson."""
    clip: str
    frames: int = 0
    detections_total: int = 0
    unique_tracks: int = 0
    line_crossings_total: int = 0
    line_crossings_by_approach: dict[str, int] = field(default_factory=dict)
    max_zone_occupancy: int = 0
    zones_sustained: dict[str, int] = field(
        default_factory=dict,
        metadata={"doc": "zone name → longest run of frames with count >= threshold"},
    )
    detections_first_quarter: int = 0
    detections_last_quarter: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ClassifierVerdict:
    clip: str
    predicted_tag: str
    predicted_confidence: float
    classifier_version: str
    pass_used: str                 # "A" or "B"
    reasons: list[str]
    features: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "predicted_tag":        self.predicted_tag,
            "predicted_confidence": round(self.predicted_confidence, 3),
            "classifier_version":   self.classifier_version,
            "pass_used":            self.pass_used,
            "reasons":              self.reasons,
        }


# ────────────────────────────────────────────────────────────────────────────
# Feature extraction
# ────────────────────────────────────────────────────────────────────────────

def _safe_json(line: str) -> dict | None:
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None


def extract_features(events_path: Path) -> ClipFeatures:
    """Aggregate a per-clip ndjson into a ClipFeatures."""
    clip_name = events_path.stem
    feats = ClipFeatures(clip=clip_name)

    # Raw events stored for downstream rule evaluation.
    zone_runs: dict[str, int] = defaultdict(int)    # current run length per zone
    zone_run_max: dict[str, int] = defaultdict(int) # longest run length per zone
    zone_kind: dict[str, str] = {}
    raw_zone_events: list[dict] = []
    frame_seen: set[int] = set()

    for raw in events_path.read_text().splitlines():
        if not raw.strip():
            continue
        evt = _safe_json(raw)
        if not evt:
            continue
        t = evt.get("event_type")

        if t == "run_end":
            # Trust run_end's summary when present — it's authoritative.
            feats.frames = int(evt.get("frames", feats.frames))
            feats.detections_total = int(evt.get("detections_total", feats.detections_total))
            feats.unique_tracks = int(evt.get("unique_tracks", feats.unique_tracks))
            lc = evt.get("line_crossings") or {}
            feats.line_crossings_by_approach = {k: int(v) for k, v in lc.items()}
            feats.line_crossings_total = sum(feats.line_crossings_by_approach.values())

        elif t == "stop_line_crossing":
            # Per-event counting (only used if run_end missing).
            if not feats.line_crossings_by_approach:
                ap = evt.get("approach", "?")
                feats.line_crossings_by_approach[ap] = (
                    feats.line_crossings_by_approach.get(ap, 0)
                    + int(evt.get("delta", 0))
                )
            f = evt.get("frame")
            if isinstance(f, int):
                frame_seen.add(f)

        elif t == "zone_occupancy":
            name = evt.get("name", "?")
            kind = evt.get("kind", "?")
            count = int(evt.get("count", 0))
            zone_kind[name] = kind
            raw_zone_events.append({"name": name, "kind": kind, "count": count,
                                    "frame": evt.get("frame", -1)})
            if count > feats.max_zone_occupancy:
                feats.max_zone_occupancy = count
            f = evt.get("frame")
            if isinstance(f, int):
                frame_seen.add(f)

    # If run_end was absent (partial ndjson), fall back to derived values.
    if not feats.line_crossings_total and feats.line_crossings_by_approach:
        feats.line_crossings_total = sum(feats.line_crossings_by_approach.values())
    if feats.frames == 0 and frame_seen:
        feats.frames = max(frame_seen) + 1

    # Zone-sustained runs: count, in event order per zone, the longest stretch
    # where count stays above the min_count_per_frame threshold. We don't know
    # threshold here, so we store the sequence of counts and let the rule
    # module compute it using thresholds. Persist only the count trace for now.
    # To avoid bloating: keep the per-zone (count, frame) sequence on the
    # dataclass via the raw_zone_events list.
    feats.zones_sustained = {}  # filled by apply_rules using thresholds

    # Quarter detection counts: require frame numbers in zone_occupancy events.
    # Fall back to splitting detections_total equally if unavailable.
    if raw_zone_events and feats.frames:
        quarter = max(feats.frames // 4, 1)
        first_cut = quarter
        last_cut = feats.frames - quarter
        # Heuristic: proxy "detection count" with "number of zone events"
        # since the ndjson doesn't track per-frame det count directly.
        feats.detections_first_quarter = sum(
            1 for e in raw_zone_events if e["frame"] < first_cut
        )
        feats.detections_last_quarter = sum(
            1 for e in raw_zone_events if e["frame"] >= last_cut
        )

    # Stash raw trace + zone_kind on the features dict for rule evaluation.
    # (We don't store on dataclass to keep the JSON small.)
    feats_extra = {"_raw_zone_events": raw_zone_events, "_zone_kind": zone_kind}
    feats.__dict__.update(feats_extra)
    return feats


# ────────────────────────────────────────────────────────────────────────────
# Pass A — rules
# ────────────────────────────────────────────────────────────────────────────

def _longest_run(counts: list[int], min_count: int) -> int:
    """Length of the longest contiguous stretch where count >= min_count."""
    best, cur = 0, 0
    for c in counts:
        if c >= min_count:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _by_zone(raw_events: list[dict]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = defaultdict(list)
    # events arrive in chronological order; group by zone name.
    for e in raw_events:
        out[e["name"]].append(int(e["count"]))
    return out


def apply_rules(feats: ClipFeatures, thresholds: dict) -> ClassifierVerdict:
    """Run Pass A rules. Returns a verdict (possibly ``insufficient_evidence``)."""
    cfg = thresholds["pass_a"]
    version = thresholds.get("version", "v1.0-rules")
    raw = feats.__dict__.get("_raw_zone_events", [])
    zone_kind = feats.__dict__.get("_zone_kind", {})
    reasons: list[str] = []
    margin = 0.0

    # --- gridlock ---
    g = cfg["gridlock"]
    if (feats.max_zone_occupancy >= g["max_zone_occupancy_min"]
            and feats.line_crossings_total <= g["line_crossings_total_max"]
            and feats.unique_tracks >= g["min_unique_tracks"]
            and feats.frames >= g["min_frames"]):
        reasons = [
            f"line_crossings_total={feats.line_crossings_total} <= {g['line_crossings_total_max']}",
            f"max_zone_occupancy={feats.max_zone_occupancy} >= {g['max_zone_occupancy_min']}",
            f"unique_tracks={feats.unique_tracks} >= {g['min_unique_tracks']}",
            f"frames={feats.frames} >= {g['min_frames']}",
        ]
        margin = (feats.max_zone_occupancy - g["max_zone_occupancy_min"])
        return _verdict(feats, "gridlock", reasons, margin, version, pass_used="A")

    # --- queue_spillback ---
    q = cfg["queue_spillback"]
    if feats.line_crossings_total <= q["max_line_crossings_total"]:
        by_zone = _by_zone(raw)
        for name, counts in by_zone.items():
            if zone_kind.get(name) != "queue_spillback":
                continue
            run = _longest_run(counts, q["min_count_per_frame"])
            if run >= q["min_sustained_frames"]:
                reasons = [
                    f"zone '{name}' stayed at count >= {q['min_count_per_frame']}"
                    f" for {run} frames (>= {q['min_sustained_frames']})",
                    f"line_crossings_total={feats.line_crossings_total} <= {q['max_line_crossings_total']}"
                    " (queue not draining)",
                ]
                margin = run - q["min_sustained_frames"]
                return _verdict(feats, "queue_spillback", reasons, margin, version, pass_used="A")

    # --- sudden_congestion ---
    s = cfg["sudden_congestion"]
    first_q, last_q = feats.detections_first_quarter, feats.detections_last_quarter
    if first_q > 0 and last_q >= first_q * s["last_quarter_multiplier"]:
        ratio = last_q / first_q
        reasons = [
            f"zone-event rate last-quarter/first-quarter={ratio:.2f}"
            f" >= {s['last_quarter_multiplier']}",
            f"(first_q={first_q}, last_q={last_q})",
        ]
        margin = ratio - s["last_quarter_multiplier"]
        return _verdict(feats, "sudden_congestion", reasons, margin, version, pass_used="A")

    # --- unexpected_trajectory ---
    u = cfg["unexpected_trajectory"]
    churn_ratio = feats.unique_tracks / max(u["baseline_tracks"], 1)
    churn_trigger = churn_ratio >= u["track_churn_ratio_min"]
    approach_trigger = False
    top_frac = 0.0
    if feats.line_crossings_total > 0:
        top = max(feats.line_crossings_by_approach.values(), default=0)
        top_frac = top / feats.line_crossings_total
        approach_trigger = top_frac >= u["approach_concentration_min"]
    if churn_trigger or approach_trigger:
        if churn_trigger:
            reasons.append(
                f"track churn {feats.unique_tracks}/{u['baseline_tracks']}"
                f"={churn_ratio:.2f} >= {u['track_churn_ratio_min']}"
            )
            margin = max(margin, churn_ratio - u["track_churn_ratio_min"])
        if approach_trigger:
            reasons.append(
                f"single-approach concentration {top_frac:.0%}"
                f" >= {u['approach_concentration_min']:.0%}"
            )
            margin = max(margin, top_frac - u["approach_concentration_min"])
        return _verdict(feats, "unexpected_trajectory", reasons, margin, version, pass_used="A")

    # --- normal ---
    n = cfg["normal"]
    approaches_with_cross = sum(1 for v in feats.line_crossings_by_approach.values() if v > 0)
    if (feats.line_crossings_total >= n["min_total_crossings"]
            and approaches_with_cross >= n["min_approaches_with_crossings"]):
        reasons = [
            f"line_crossings_total={feats.line_crossings_total} >= {n['min_total_crossings']}",
            f"approaches_with_crossings={approaches_with_cross} >= {n['min_approaches_with_crossings']}",
        ]
        margin = (feats.line_crossings_total - n["min_total_crossings"])
        return _verdict(feats, "normal", reasons, margin, version, pass_used="A")

    # --- fall-through ---
    return _verdict(
        feats,
        "insufficient_evidence",
        [
            "no Pass A rule triggered",
            f"line_crossings_total={feats.line_crossings_total}",
            f"max_zone_occupancy={feats.max_zone_occupancy}",
            f"unique_tracks={feats.unique_tracks}",
        ],
        margin=0.0,
        version=version,
        pass_used="A",
    )


def _confidence(margin: float, cfg: dict) -> float:
    floor = cfg["floor"]
    saturate = cfg["saturate_at"]
    if margin <= 0:
        return floor
    if margin >= saturate:
        return 0.99
    # Linear between floor and 0.99 from [0, saturate].
    return floor + (0.99 - floor) * (margin / saturate)


def _verdict(
    feats: ClipFeatures,
    tag: str,
    reasons: list[str],
    margin: float,
    version: str,
    pass_used: str,
) -> ClassifierVerdict:
    # Lookup confidence config via closure? We'll pass via a module cache.
    cfg = _THRESHOLDS_CACHE.get("confidence", {"floor": 0.5, "saturate_at": 3.0})
    conf = _confidence(margin, cfg) if tag != "insufficient_evidence" else 0.0
    features_summary = {
        "frames": feats.frames,
        "detections_total": feats.detections_total,
        "unique_tracks": feats.unique_tracks,
        "line_crossings_total": feats.line_crossings_total,
        "line_crossings_by_approach": feats.line_crossings_by_approach,
        "max_zone_occupancy": feats.max_zone_occupancy,
    }
    return ClassifierVerdict(
        clip=feats.clip,
        predicted_tag=tag,
        predicted_confidence=conf,
        classifier_version=version,
        pass_used=pass_used,
        reasons=reasons,
        features=features_summary,
    )


# ────────────────────────────────────────────────────────────────────────────
# Pass B — video re-sample (deferred import so Pass A has no hard dep on cv2)
# ────────────────────────────────────────────────────────────────────────────

def run_pass_b(
    clip_stem: str,
    normalized_dir: Path,
    metadata_path: Path,
    thresholds: dict,
    version: str,
) -> ClassifierVerdict | None:
    """Second-pass sampling of the video file. Returns None on failure."""
    video_path = normalized_dir / f"{clip_stem}.mp4"
    if not video_path.exists():
        return None
    try:
        import cv2                                  # noqa: WPS433
        import numpy as np                          # noqa: WPS433
        import supervision as sv                    # noqa: WPS433
        from ultralytics import YOLO                # noqa: WPS433
        from .zones import load_stop_lines, load_zones
    except Exception as exc:                        # noqa: BLE001
        return ClassifierVerdict(
            clip=clip_stem,
            predicted_tag="insufficient_evidence",
            predicted_confidence=0.0,
            classifier_version=version,
            pass_used="B",
            reasons=[f"Pass B unavailable: {exc}"],
            features={},
        )

    pb_cfg = thresholds["pass_b"]
    step = int(pb_cfg["sample_every_n_frames"])
    min_samples = int(pb_cfg["min_track_samples"])

    # Stream frames ourselves to control sampling rate.
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    sample_dt = step / fps                          # seconds between samples
    sampled_frames: list[tuple[int, np.ndarray]] = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            sampled_frames.append((i, frame))
        i += 1
    cap.release()

    if len(sampled_frames) < min_samples:
        return ClassifierVerdict(
            clip=clip_stem,
            predicted_tag="insufficient_evidence",
            predicted_confidence=0.0,
            classifier_version=version,
            pass_used="B",
            reasons=[f"only {len(sampled_frames)} samples (< {min_samples})"],
            features={},
        )

    model = YOLO(str(REPO_ROOT / "models/yolo26n.pt"))
    classes = [2, 3, 5, 7, pb_cfg["pedestrian_interaction"]["coco_pedestrian_class_id"]]

    # Track across sampled frames via the Ultralytics tracker.
    track_positions: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
    track_class: dict[int, int] = {}
    for frame_idx, bgr in sampled_frames:
        res = model.track(bgr, persist=True, classes=classes, verbose=False)[0]
        det = sv.Detections.from_ultralytics(res)
        if det.tracker_id is None or len(det) == 0:
            continue
        for j in range(len(det)):
            tid = det.tracker_id[j]
            if tid is None:
                continue
            x1, y1, x2, y2 = det.xyxy[j]
            cx, cy = float((x1 + x2) / 2), float((y1 + y2) / 2)
            track_positions[int(tid)].append((frame_idx, cx, cy))
            if det.class_id is not None:
                track_class[int(tid)] = int(det.class_id[j])

    zones = load_zones(metadata_path)
    ped_zones = [z for z in zones if z.kind in pb_cfg["pedestrian_interaction"]["adjacent_zone_kinds"]]
    stalled_exclude_zones = [z for z in zones if z.kind == "queue_spillback"]
    abnormal_include_zones = [z for z in zones if z.kind in pb_cfg["abnormal_stop"]["inside_zone_kinds"]]

    # Compute mean speed per track.
    reasons: list[str] = []
    stalled_candidates: list[int] = []
    abnormal_candidates: list[int] = []
    pedestrian_present = False
    for tid, trace in track_positions.items():
        if len(trace) < min_samples:
            continue
        dxs = [(trace[k][1] - trace[k - 1][1], trace[k][2] - trace[k - 1][2])
               for k in range(1, len(trace))]
        dts = [(trace[k][0] - trace[k - 1][0]) / fps for k in range(1, len(trace))]
        if not dts or min(dts) == 0:
            continue
        speeds = [((dx * dx + dy * dy) ** 0.5) / dt for (dx, dy), dt in zip(dxs, dts)]
        if not speeds:
            continue
        mean_speed = sum(speeds) / len(speeds)
        last_pt = (trace[-1][1], trace[-1][2])
        if track_class.get(tid) == pb_cfg["pedestrian_interaction"]["coco_pedestrian_class_id"]:
            if any(_point_in_zone(last_pt, z) for z in ped_zones):
                pedestrian_present = True
            continue
        if mean_speed < pb_cfg["stalled_vehicle"]["max_mean_speed_pxps"]:
            if any(_point_in_zone(last_pt, z) for z in abnormal_include_zones):
                abnormal_candidates.append(tid)
            elif not any(_point_in_zone(last_pt, z) for z in stalled_exclude_zones):
                stalled_candidates.append(tid)

    if abnormal_candidates:
        reasons.append(f"{len(abnormal_candidates)} tracks stationary inside travel lanes")
        tag = "abnormal_stop"
    elif stalled_candidates:
        reasons.append(f"{len(stalled_candidates)} tracks stationary outside queue zones")
        tag = "stalled_vehicle"
    elif pedestrian_present:
        reasons.append("pedestrian detected inside a ped_crossing zone")
        tag = "pedestrian_interaction"
    else:
        reasons.append("Pass B sampled motion did not trigger any rule")
        tag = "insufficient_evidence"

    return ClassifierVerdict(
        clip=clip_stem,
        predicted_tag=tag,
        predicted_confidence=0.6 if tag != "insufficient_evidence" else 0.0,
        classifier_version=version,
        pass_used="B",
        reasons=reasons,
        features={
            "sampled_frames": len(sampled_frames),
            "tracks_sampled": len(track_positions),
            "stalled_candidates": len(stalled_candidates),
            "abnormal_candidates": len(abnormal_candidates),
            "pedestrian_present": pedestrian_present,
        },
    )


def _point_in_zone(pt, named_zone) -> bool:
    import cv2  # noqa: WPS433
    import numpy as np
    poly = np.asarray(named_zone.zone.polygon, dtype=np.int32)
    return cv2.pointPolygonTest(poly, pt, False) >= 0


# ────────────────────────────────────────────────────────────────────────────
# Top-level API
# ────────────────────────────────────────────────────────────────────────────

_THRESHOLDS_CACHE: dict = {}


def load_thresholds(path: Path) -> dict:
    with path.open() as fh:
        th = yaml.safe_load(fh)
    _THRESHOLDS_CACHE.clear()
    _THRESHOLDS_CACHE.update(th)
    return th


def classify_clip(
    events_path: Path,
    thresholds_path: Path = DEFAULT_THRESHOLDS,
    metadata_path: Path = DEFAULT_METADATA,
    normalized_dir: Path | None = None,
) -> ClassifierVerdict:
    thresholds = load_thresholds(thresholds_path)
    feats = extract_features(events_path)
    verdict = apply_rules(feats, thresholds)
    if verdict.predicted_tag == "insufficient_evidence" and normalized_dir is not None:
        pb = run_pass_b(
            feats.clip,
            normalized_dir,
            metadata_path,
            thresholds,
            thresholds.get("version", "v1.0-rules"),
        )
        if pb is not None:
            return pb
    return verdict


def update_manifest(manifest_path: Path, verdicts: list[ClassifierVerdict]) -> None:
    """Merge verdicts into clips_manifest.json, preserving human `tag` field."""
    by_clip = {v.clip: v for v in verdicts}
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        "version": 1, "clips": []
    }
    clips = manifest.get("clips", [])
    for c in clips:
        name = c.get("clip")
        if name in by_clip:
            c.update(by_clip.pop(name).to_dict())
    # Any remaining clips not already in the manifest get appended as stubs.
    for name, v in by_clip.items():
        clips.append({"clip": name, **v.to_dict()})
    manifest["clips"] = clips
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rule-based event classifier (Phase 1 §6.6).")
    p.add_argument("events", nargs="?", type=Path,
                   help="Single ndjson path. Omit with --batch.")
    p.add_argument("--batch", action="store_true",
                   help=f"Process every *.ndjson under {DEFAULT_EVENTS_DIR}")
    p.add_argument("--events-dir", type=Path, default=DEFAULT_EVENTS_DIR)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--update-manifest", action="store_true",
                   help="Merge verdicts into clips_manifest.json")
    p.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    p.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    p.add_argument("--normalized-dir", type=Path, default=None,
                   help="If set, Pass B runs on insufficient-evidence clips using "
                        "<normalized-dir>/<clip>.mp4")
    args = p.parse_args(argv)

    verdicts: list[ClassifierVerdict] = []
    if args.batch:
        targets = sorted(args.events_dir.glob("*.ndjson"))
    elif args.events:
        targets = [args.events]
    else:
        p.error("either <events> or --batch is required")
        return 2

    for events_path in targets:
        v = classify_clip(
            events_path,
            thresholds_path=args.thresholds,
            metadata_path=args.metadata,
            normalized_dir=args.normalized_dir,
        )
        verdicts.append(v)
        print(json.dumps({
            "clip": v.clip,
            **v.to_dict(),
        }, indent=2), file=sys.stdout)

    if args.update_manifest and verdicts:
        update_manifest(args.manifest, verdicts)
        print(f"\n[classifier] updated {args.manifest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
