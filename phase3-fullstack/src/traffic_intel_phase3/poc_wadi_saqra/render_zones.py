"""Render approach-zone overlay on a reference frame for visual verification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

APPROACH_COLOR = {
    "S": (102, 255, 136),   # RGB #66ff88 green
    "N": (122, 122, 255),   # RGB #ff7a7a red
    "E": (60, 165, 245),    # RGB #f5a53c orange
    "W": (203, 172, 74),    # RGB #4aaccb blue
}


def render(frame_path: Path, zones_path: Path, out_path: Path) -> Path:
    img = cv2.imread(str(frame_path))
    if img is None:
        raise FileNotFoundError(f"could not read frame: {frame_path}")

    zones = json.loads(zones_path.read_text())
    overlay = img.copy()

    for z in zones["zones"]:
        color = APPROACH_COLOR.get(z["approach"], (200, 200, 200))
        pts = np.array(z["polygon"], dtype=np.int32)
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(img, [pts], isClosed=True, color=color, thickness=3)
        sl = z.get("stop_line")
        if sl:
            cv2.line(img, tuple(sl[0]), tuple(sl[1]), (0, 255, 255), 4)
        cx = int(np.mean(pts[:, 0])); cy = int(np.mean(pts[:, 1]))
        cv2.putText(img, z["approach"], (cx - 18, cy + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 6, cv2.LINE_AA)
        cv2.putText(img, z["approach"], (cx - 18, cy + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, color, 3, cv2.LINE_AA)

    blended = cv2.addWeighted(overlay, 0.30, img, 0.70, 0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), blended)
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", type=Path, required=True)
    ap.add_argument("--zones", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    out = render(args.frame, args.zones, args.out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
