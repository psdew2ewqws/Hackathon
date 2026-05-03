"""Trajectory-driven lane induction for the live tracker.

Phase 1.5 of the production-readiness plan. We induce lane geometry from
the per-vehicle trajectories ByteTrack already produces — dashcam-trained
ML lane detectors (LaneNet, UFLD, CLRNet) are a poor fit for our oblique
stationary-camera view. The literature (Ren 2014 et al.) reports ~95%
lane-detection accuracy on urban intersections using approach-conditioned
trajectory clustering, which is the algorithm implemented here.

Pipeline:
    raw trajectories (list of (tid, approach, centroids))
    → bucket by approach
    → arc-length resample each track to N points
    → pairwise discrete Fréchet distance matrix
    → DBSCAN with metric="precomputed"
    → per-cluster centerline (medial line) + ±lane_width/2 polygon
    → lane_type label from exit-vs-entry direction

Pure functions; no I/O. The HTTP layer (server.py) and the live tracker
buffer (trajectory_buffer.py) call this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from .counters import Zone, point_in_polygon


# Default tunables. The defaults are calibrated for 1080p with a typical
# urban intersection at ~30° camera elevation. Operators can override.
DEFAULT_RESAMPLE_N = 32
# Empirically tuned against the Wadi Saqra trajectories.ndjson sample
# (1080p oblique view). At 1080p the mean trajectory-to-trajectory
# Fréchet distance is ~300 px, so eps=80 admits cohesive lane corridors
# without merging cross-traffic.
DEFAULT_DBSCAN_EPS = 80.0          # pixels
DEFAULT_DBSCAN_MIN_SAMPLES = 5
DEFAULT_LANE_WIDTH_PX = 60.0
DEFAULT_LANE_TYPE_ANGLE_DEG = 25.0  # turns >25° are left/right, else "through"
DEFAULT_MAX_TRACKS_PER_APPROACH = 60  # pure-python Fréchet is O(n²) — cap to ~3.5k pairs
# Trajectory pre-filter: drop tracks whose total path length is below this
# threshold. Removes the queue-bias problem where vehicles waiting at the
# stop line dominate the centroid distribution and pull cluster centerlines
# toward the queue zone instead of the actual driving lane.
DEFAULT_MIN_DISPLACEMENT_PX = 120.0


@dataclass
class LaneSpec:
    """One induced lane, ready to persist into wadi_saqra_zones.json."""
    approach: str
    lane_id: str
    lane_idx: int
    lane_type: str             # "left" | "through" | "right" | "shared"
    polygon: np.ndarray        # (M, 2) int32, perspective-correct (not axis-aligned)
    centerline: np.ndarray     # (N, 2) float, the cluster medial line
    sample_count: int = 0      # how many trajectories contributed (for confidence)


# ---------------- discrete Fréchet ----------------

def discrete_frechet(p: np.ndarray, q: np.ndarray) -> float:
    """Discrete Fréchet distance between two polylines (Eiter & Mannila 1994).

    Both inputs are (N, 2) and (M, 2) numpy arrays of 2D points. O(N*M) time
    and memory; for our N=M=32 that's ~1024 ops per pair — cheap enough.
    """
    n, m = len(p), len(q)
    if n == 0 or m == 0:
        return float("inf")
    ca = np.full((n, m), -1.0)
    # Dynamic-programming table; Eiter-Mannila recurrence.
    ca[0, 0] = float(np.linalg.norm(p[0] - q[0]))
    for i in range(1, n):
        ca[i, 0] = max(ca[i - 1, 0], float(np.linalg.norm(p[i] - q[0])))
    for j in range(1, m):
        ca[0, j] = max(ca[0, j - 1], float(np.linalg.norm(p[0] - q[j])))
    for i in range(1, n):
        for j in range(1, m):
            d = float(np.linalg.norm(p[i] - q[j]))
            ca[i, j] = max(min(ca[i - 1, j], ca[i - 1, j - 1], ca[i, j - 1]), d)
    return float(ca[n - 1, m - 1])


# ---------------- arc-length resample ----------------

def resample_trajectory(track: np.ndarray, n: int = DEFAULT_RESAMPLE_N) -> np.ndarray:
    """Resample a polyline to ``n`` equally arc-length-spaced points.

    Endpoints of the original are preserved exactly so straight tracks
    remain straight after resampling.
    """
    if len(track) < 2:
        return np.repeat(track[:1], n, axis=0)
    seg = np.linalg.norm(np.diff(track, axis=0), axis=1)
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    total = cum[-1]
    if total == 0:
        return np.repeat(track[:1], n, axis=0)
    targets = np.linspace(0, total, n)
    out = np.empty((n, 2), dtype=float)
    for i, t in enumerate(targets):
        idx = np.searchsorted(cum, t, side="right") - 1
        idx = max(0, min(idx, len(track) - 2))
        denom = cum[idx + 1] - cum[idx]
        u = 0.0 if denom == 0 else (t - cum[idx]) / denom
        out[i] = (1 - u) * track[idx] + u * track[idx + 1]
    return out


# ---------------- lane-type inference ----------------

def infer_lane_type(track: np.ndarray, angle_thresh_deg: float = DEFAULT_LANE_TYPE_ANGLE_DEG) -> str:
    """Label a trajectory as "through" / "left" / "right" by exit-vs-entry angle.

    "left" and "right" are reported in image coords (y axis points DOWN, as
    is standard for screen pixels), so a track that enters going down and
    exits going right is labeled "right" in screen sense.
    """
    if len(track) < 4:
        return "through"
    # Average direction over the first vs last 25% of the track (more
    # robust than just the first/last segment).
    n = len(track)
    head_n = max(2, n // 4)
    enter_dir = track[head_n] - track[0]
    exit_dir = track[-1] - track[-1 - head_n]
    if np.linalg.norm(enter_dir) < 1e-6 or np.linalg.norm(exit_dir) < 1e-6:
        return "through"
    enter_dir = enter_dir / np.linalg.norm(enter_dir)
    exit_dir = exit_dir / np.linalg.norm(exit_dir)
    # 2-D cross product sign tells us turn direction; dot tells angle.
    cross = enter_dir[0] * exit_dir[1] - enter_dir[1] * exit_dir[0]
    dot = float(np.clip(np.dot(enter_dir, exit_dir), -1.0, 1.0))
    angle_deg = float(np.degrees(np.arccos(dot)))
    if angle_deg < angle_thresh_deg:
        return "through"
    return "right" if cross > 0 else "left"


# ---------------- centerline + polygon ----------------

def _centerline(member_tracks: list[np.ndarray]) -> np.ndarray:
    """Centerline of a cluster.

    Per-arc-length-bin mean across members collapses to a tiny region
    when members have very different real lengths (arc-length resample
    treats a 50px track and a 600px track as 32 evenly-spaced points
    each). Instead, anchor on the cluster's LONGEST member — that
    guarantees the centerline spans the actual lane corridor — then
    smooth lightly with the bin-mean as a regularizer.
    """
    if not member_tracks:
        return np.zeros((0, 2), dtype=float)
    # Pick the member with the largest total arc-length.
    lengths = [
        float(np.sum(np.linalg.norm(np.diff(t, axis=0), axis=1)))
        for t in member_tracks
    ]
    longest = member_tracks[int(np.argmax(lengths))]
    if len(member_tracks) < 3:
        return longest
    # Light smoothing toward the bin-mean so a single outlier doesn't dominate.
    bin_mean = np.stack(member_tracks, axis=0).mean(axis=0)
    return 0.7 * longest + 0.3 * bin_mean


def _polygon_from_centerline(
    centerline: np.ndarray, half_width_px: float
) -> np.ndarray:
    """Inflate a centerline polyline by ±half_width_px perpendicular to
    the local tangent — yields a closed polygon (left side + reversed right)."""
    n = len(centerline)
    if n < 2:
        return np.array([centerline[0]] * 4, dtype=np.int32)
    # Tangent direction at each vertex (forward differences, last vertex
    # mirrors).
    t = np.empty_like(centerline)
    t[:-1] = np.diff(centerline, axis=0)
    t[-1] = t[-2]
    # Normalize and rotate 90° to get the perpendicular.
    norms = np.linalg.norm(t, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    t = t / norms
    perp = np.column_stack([-t[:, 1], t[:, 0]])  # rotate +90°
    left = centerline + half_width_px * perp
    right = centerline - half_width_px * perp
    poly = np.vstack([left, right[::-1]]).astype(np.int32)
    return poly


# ---------------- approach bucketing ----------------

def _entry_approach(centroids: np.ndarray, zones: list[Zone]) -> str | None:
    """First approach polygon the trajectory entered (by checking the
    first 3 centroid positions)."""
    for xy in centroids[: min(3, len(centroids))]:
        for zone in zones:
            if point_in_polygon((float(xy[0]), float(xy[1])), zone.polygon):
                return zone.approach
    return None


# ---------------- main entrypoint ----------------

def _track_displacement(centroids: np.ndarray) -> float:
    """Total polyline arc-length of a trajectory in pixels."""
    if len(centroids) < 2:
        return 0.0
    return float(np.sum(np.linalg.norm(np.diff(centroids, axis=0), axis=1)))


def induce_lanes_from_trajectories(
    trajectories: Iterable[dict],
    approach_zones: list[Zone],
    *,
    min_samples: int = DEFAULT_DBSCAN_MIN_SAMPLES,
    eps: float = DEFAULT_DBSCAN_EPS,
    resample_n: int = DEFAULT_RESAMPLE_N,
    lane_width_px: float = DEFAULT_LANE_WIDTH_PX,
    max_tracks_per_approach: int = DEFAULT_MAX_TRACKS_PER_APPROACH,
    min_displacement_px: float = DEFAULT_MIN_DISPLACEMENT_PX,
) -> dict[str, list[LaneSpec]]:
    """Cluster trajectories per approach into lane proposals.

    Each input trajectory is a dict with keys:
      - ``tid``: int, the track id
      - ``approach``: str | None, optionally pre-bucketed
      - ``centroids``: (N, 2) ndarray, the per-frame (x, y) positions

    Returns ``{approach_name: [LaneSpec, ...]}``. Approaches with too few
    trajectories (< min_samples) are absent from the output.
    """
    from sklearn.cluster import DBSCAN

    # 1. Bucket by approach + drop near-stationary trajectories.
    # Vehicles that idle at the stop line dominate centroid mass otherwise
    # and pull cluster centerlines into the queue zone — clustering then
    # produces tiny "lane" polygons that look like the queue, not the lane.
    by_approach: dict[str, list[np.ndarray]] = {z.approach: [] for z in approach_zones}
    for t in trajectories:
        cents = np.asarray(t["centroids"], dtype=float)
        if len(cents) < 3:
            continue
        if _track_displacement(cents) < min_displacement_px:
            continue
        approach = t.get("approach") or _entry_approach(cents, approach_zones)
        if approach is None or approach not in by_approach:
            continue
        by_approach[approach].append(cents)

    out: dict[str, list[LaneSpec]] = {}
    for approach, tracks in by_approach.items():
        if len(tracks) < min_samples:
            continue
        # Cap per-approach tracks to keep the O(n²) Fréchet matrix bounded.
        # 120 tracks ⇒ ~14k Fréchet pairs ⇒ <1s in pure Python.
        if len(tracks) > max_tracks_per_approach:
            idx = np.random.default_rng(0).choice(
                len(tracks), size=max_tracks_per_approach, replace=False,
            )
            tracks = [tracks[int(i)] for i in idx]
        resampled = [resample_trajectory(tr, n=resample_n) for tr in tracks]
        # Pairwise Fréchet distance matrix.
        n = len(resampled)
        dmat = np.zeros((n, n), dtype=float)
        for i in range(n):
            for j in range(i + 1, n):
                d = discrete_frechet(resampled[i], resampled[j])
                dmat[i, j] = d
                dmat[j, i] = d
        # DBSCAN on the precomputed distances.
        labels = DBSCAN(
            eps=eps, min_samples=min_samples, metric="precomputed"
        ).fit_predict(dmat)
        unique = sorted(int(L) for L in set(labels) if L != -1)
        if not unique:
            continue
        lane_specs: list[LaneSpec] = []
        for cluster_id in unique:
            members = [resampled[i] for i in range(n) if labels[i] == cluster_id]
            centerline = _centerline(members)
            polygon = _polygon_from_centerline(centerline, lane_width_px / 2.0)
            lane_type = infer_lane_type(centerline)
            lane_specs.append(LaneSpec(
                approach=approach,
                lane_id="",            # filled below after sorting
                lane_idx=0,            # filled below after sorting
                lane_type=lane_type,
                polygon=polygon,
                centerline=centerline,
                sample_count=len(members),
            ))
        # Order lanes left-to-right (or top-to-bottom) by centerline
        # midpoint along the dominant axis of the approach.
        lane_specs.sort(key=lambda ls: float(ls.centerline[len(ls.centerline) // 2, 0]))
        for idx, ls in enumerate(lane_specs):
            ls.lane_idx = idx
            ls.lane_id = f"{approach}-{idx + 1}"
        out[approach] = lane_specs
    return out


# ---------------- drift check ----------------

def hausdorff(a: np.ndarray, b: np.ndarray) -> float:
    """Symmetric Hausdorff distance between two point sets."""
    if len(a) == 0 or len(b) == 0:
        return float("inf")
    diff_a_to_b = np.array([
        float(np.min(np.linalg.norm(b - p, axis=1))) for p in a
    ])
    diff_b_to_a = np.array([
        float(np.min(np.linalg.norm(a - p, axis=1))) for p in b
    ])
    return float(max(diff_a_to_b.max(), diff_b_to_a.max()))


def lane_geometry_drift(
    saved: list[LaneSpec], induced: list[LaneSpec]
) -> float:
    """Max per-lane Hausdorff between saved and freshly-induced centerlines.

    Returns inf when the lane counts differ — that's the strongest signal.
    """
    if len(saved) != len(induced):
        return float("inf")
    saved_sorted = sorted(saved, key=lambda L: L.lane_idx)
    induced_sorted = sorted(induced, key=lambda L: L.lane_idx)
    return max(
        hausdorff(s.centerline, i.centerline)
        for s, i in zip(saved_sorted, induced_sorted)
    )
