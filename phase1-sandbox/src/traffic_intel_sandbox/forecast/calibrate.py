"""Extract a keyframe from the user's anchor video and author a
forecast_site.json with default stop-line polygons + monitoring zones.

Defaults are placed based on the observation that the anchor video
(/home/admin1/Downloads/Traffic Video .mp4) shows a 4-way signalized
intersection in the lower-center of the frame at 1920x1080. These defaults
are a *starting point* — the user can edit forecast_site.json and re-run
``forecast-observe`` to iterate.

Outputs:
    data/forecast/anchor_frame.jpg     — middle frame of the video
    data/forecast/anchor_overlay.jpg   — same frame with stop-lines drawn
    data/forecast/forecast_site.json   — site metadata in site1.example.json
                                          format (consumable by detect_track.py)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


# Reasonable defaults for the 1920x1080 anchor frame.
# Frame-orientation convention (caller can remap at view-time):
#   TOP    = N  (cars entering from upper approach)
#   BOTTOM = S
#   RIGHT  = E
#   LEFT   = W
# The stop-line polyline is drawn at the inner edge of the intersection
# on that side, so vehicles crossing the polyline INTO the junction box
# get counted toward that approach.
#
# Coordinates tuned by visually inspecting anchor_frame.jpg for
# Traffic Video .mp4: intersection core spans roughly
# x ∈ [350, 1300], y ∈ [400, 900] at 1920×1080.

# Defaults tuned for the YouTube anchor video (52ao3WsInBo) at 1920x1080.
# This shot is an oblique elevated view of a wide 4-way signalised intersection
# in Amman. The N-S cross-street is narrow and roughly centred horizontally;
# the E-W arterial is wider and runs across the middle of the frame.
#
# Intersection core approximate bounds: x ∈ [400, 1500], y ∈ [280, 720].
# Stop-lines are placed at the inner edges of that core, on the incoming side.

# Zones tuned to land on actual roadway — off buildings, off parking lots.
# Anchored on the visible intersection in the YouTube Amman CCTV clip:
#   - Upper arterial (cars driving left→right across the top) = "N approach"
#   - Lower arterial (cars driving right→left in the middle)  = "S approach"  (see note)
#   - Incoming from the right foreground                      = "E approach"
#   - Incoming from the left foreground                       = "W approach"
# Note the cardinal labels are topological, not true compass — the intersection
# is skewed and the handbook only requires the pipeline to be labeled
# consistently, which is what these zones do.

DEFAULTS_1920x1080 = {
    "stop_lines": [
        # Upper arterial: catch cars on the top road crossing L→R
        {"approach": "N", "polyline_px": [[260, 290],  [900, 290]]},
        # Lower arterial / foreground cross-street: near the bottom crosswalk
        {"approach": "S", "polyline_px": [[380, 610],  [1020, 610]]},
        # Right-side approach: cars coming in from the right foreground
        {"approach": "E", "polyline_px": [[980, 370],  [980, 540]]},
        # Left-side approach: cars coming in from the left foreground
        {"approach": "W", "polyline_px": [[320, 370],  [320, 540]]},
    ],
    "monitoring_zones": [
        # N: upper arterial — the visible top road only (above the median)
        {"name": "queue_spillback_N", "kind": "queue_spillback",
         "polygon_px": [[180, 210],   [920, 210],  [920, 320], [180, 320]]},
        # S: the intersection-bottom area between the crosswalk and the median
        {"name": "queue_spillback_S", "kind": "queue_spillback",
         "polygon_px": [[380, 580],   [1040, 580], [1040, 720], [380, 720]]},
        # E: right approach — the visible approach lane only, not the parking
        {"name": "queue_spillback_E", "kind": "queue_spillback",
         "polygon_px": [[940, 340],   [1240, 340], [1240, 560], [940, 560]]},
        # W: left approach — the lane coming in from the left, not the parking
        {"name": "queue_spillback_W", "kind": "queue_spillback",
         "polygon_px": [[260, 340],   [540, 340],  [540, 560],  [260, 560]]},
        # Intersection core (just for outline)
        {"name": "conflict_zone_center", "kind": "conflict_zone",
         "polygon_px": [[540, 320],   [940, 320],  [940, 560], [540, 560]]},
    ],
}


APPROACH_COLORS = {
    "N": (100, 220, 255),   # light blue
    "S": (255, 160, 100),   # orange
    "E": (120, 255, 160),   # green
    "W": (200, 140, 255),   # purple
}


def extract_keyframe(video: Path, out_jpg: Path, at_s: float = 4.0) -> None:
    """Pull a single frame at ~4s into the 8s video via ffmpeg."""
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(at_s), "-i", str(video),
        "-frames:v", "1", "-q:v", "2", str(out_jpg),
    ], check=True)


def draw_overlay(frame_jpg: Path, site: dict, out_jpg: Path) -> None:
    """Render stop-line polylines + zone polygons onto the keyframe so the
    user can visually verify the calibration before running YOLO."""
    img = cv2.imread(str(frame_jpg))
    if img is None:
        raise RuntimeError(f"couldn't read {frame_jpg}")
    overlay = img.copy()

    # zones first (semi-transparent fills so stop-lines draw over them)
    for zone in site["monitoring_zones"]:
        pts = np.array(zone["polygon_px"], dtype=np.int32)
        name = zone["name"]
        if name.startswith("queue_spillback_"):
            appr = name.split("_")[-1]
            color = APPROACH_COLORS.get(appr, (180, 180, 180))
            cv2.fillPoly(overlay, [pts], color)
        elif zone["kind"] == "conflict_zone":
            cv2.polylines(overlay, [pts], True, (255, 255, 255), 2)
    img = cv2.addWeighted(overlay, 0.18, img, 0.82, 0)

    # stop-lines on top
    for sl in site["stop_lines"]:
        appr = sl["approach"]
        color = APPROACH_COLORS.get(appr, (255, 255, 255))
        pts = np.array(sl["polyline_px"], dtype=np.int32)
        cv2.polylines(img, [pts], False, color, 5)
        # label midpoint
        mid = pts.mean(axis=0).astype(int)
        label_pos = (int(mid[0]) - 14, int(mid[1]) - 12)
        cv2.rectangle(img,
                      (label_pos[0] - 4, label_pos[1] - 24),
                      (label_pos[0] + 30, label_pos[1] + 6),
                      color, -1)
        cv2.putText(img, appr, label_pos,
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2, cv2.LINE_AA)

    # small legend
    legend_y = 30
    for appr in ("N", "S", "E", "W"):
        cv2.rectangle(img, (20, legend_y - 18), (44, legend_y + 4),
                      APPROACH_COLORS[appr], -1)
        cv2.putText(img, f"{appr} approach", (54, legend_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
                    cv2.LINE_AA)
        legend_y += 28

    cv2.imwrite(str(out_jpg), img)


def build_site_meta(width: int, height: int,
                    center_lat: float, center_lon: float,
                    rtsp_url: str) -> dict:
    """Emit a site JSON that detect_track.py + zones.py can load directly."""
    if (width, height) != (1920, 1080):
        raise NotImplementedError(
            f"Default stop-lines are tuned for 1920x1080, got {width}x{height}. "
            f"Edit calibrate.py or the generated forecast_site.json.")
    return {
        "intersection_id": "SITE-GMAPS",
        "location": {
            "city": "Amman",
            "country": "Jordan",
            "lat": center_lat,
            "lon": center_lon,
        },
        "camera": {
            "stream_url": rtsp_url,
            "resolution": [width, height],
            "fps": 10,
            "fov_deg": 90,
            "mounting_height_m": 15.0,
            "bearing_deg": 180,
        },
        # Keep site1.example.json's approach schema so downstream scripts
        # (classifier, zones) don't need to branch. Lane counts are a guess
        # for the video — phase 2 only uses them for per-lane breakdown,
        # which we don't consume in the forecast path.
        "approaches": [
            {"name": "N", "direction_bearing_deg": 0,
             "lanes": [{"id": "N-1", "type": "right",   "detector_id": "DET-N-1-1", "width_m": 3.2},
                       {"id": "N-2", "type": "through", "detector_id": "DET-N-2-1", "width_m": 3.5},
                       {"id": "N-3", "type": "left",    "detector_id": "DET-N-3-1", "width_m": 3.2}]},
            {"name": "S", "direction_bearing_deg": 180,
             "lanes": [{"id": "S-1", "type": "right",   "detector_id": "DET-S-1-1", "width_m": 3.2},
                       {"id": "S-2", "type": "through", "detector_id": "DET-S-2-1", "width_m": 3.5},
                       {"id": "S-3", "type": "left",    "detector_id": "DET-S-3-1", "width_m": 3.2}]},
            {"name": "E", "direction_bearing_deg": 90,
             "lanes": [{"id": "E-1", "type": "right",   "detector_id": "DET-E-1-1", "width_m": 3.2},
                       {"id": "E-2", "type": "through", "detector_id": "DET-E-2-1", "width_m": 3.5},
                       {"id": "E-3", "type": "left",    "detector_id": "DET-E-3-1", "width_m": 3.2}]},
            {"name": "W", "direction_bearing_deg": 270,
             "lanes": [{"id": "W-1", "type": "right",   "detector_id": "DET-W-1-1", "width_m": 3.2},
                       {"id": "W-2", "type": "through", "detector_id": "DET-W-2-1", "width_m": 3.5},
                       {"id": "W-3", "type": "left",    "detector_id": "DET-W-3-1", "width_m": 3.2}]},
        ],
        **DEFAULTS_1920x1080,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--video", type=Path,
                   default=Path("/home/admin1/TheVideo.mp4"))
    p.add_argument("--out-dir", type=Path, default=Path("data/forecast"))
    p.add_argument("--center-lat", type=float, default=31.96686)
    p.add_argument("--center-lon", type=float, default=35.88704)
    p.add_argument("--rtsp-url",   default="file:///home/admin1/TheVideo.mp4")
    p.add_argument("--keyframe-at-s", type=float, default=30.0)
    args = p.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    frame_path   = args.out_dir / "anchor_frame.jpg"
    overlay_path = args.out_dir / "anchor_overlay.jpg"
    site_path    = args.out_dir / "forecast_site.json"

    extract_keyframe(args.video, frame_path, args.keyframe_at_s)

    # confirm resolution from the real frame
    img = cv2.imread(str(frame_path))
    if img is None:
        raise RuntimeError(f"couldn't read the extracted frame {frame_path}")
    h, w = img.shape[:2]

    site = build_site_meta(w, h, args.center_lat, args.center_lon, args.rtsp_url)
    site_path.write_text(json.dumps(site, indent=2))
    draw_overlay(frame_path, site, overlay_path)

    print(f"[calibrate] frame    → {frame_path}")
    print(f"[calibrate] site     → {site_path}")
    print(f"[calibrate] overlay  → {overlay_path}  (review + edit stop-lines if wrong)")
    print(f"[calibrate] frame resolution: {w}x{h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
