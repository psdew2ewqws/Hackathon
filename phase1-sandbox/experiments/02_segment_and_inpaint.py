"""Experiment 02 — Segment vehicles and build a clean background plate.

Stage 2 of the sim-to-real pipeline (see docs/research_sim_to_real.md).

Reads frames produced by 01_extract_wadisaqra_frames.py and, for each frame:
  - runs a vehicle+pedestrian instance segmenter (Grounded-SAM 2 preferred,
    Ultralytics YOLO-seg fallback, OpenCV HOG fallback-fallback)
  - saves per-frame instance masks (one COCO-style JSON per frame)
  - saves per-instance alpha-masked vehicle crops for compositing
  - computes a union mask per video and runs LaMa (or a median/OpenCV fallback)
    to produce one clean background plate.

Graceful degradation: if the preferred weights/libs aren't installed, falls
back through a documented chain so the smoke test still runs on CPU-only
with zero extra downloads. The research doc lists the full set of preferred
models.

Usage
-----
    python experiments/02_segment_and_inpaint.py \\
        --frames-dir data/research/frames \\
        --out-segments data/research/segments \\
        --out-crops data/research/crops \\
        --out-plates data/research/plates \\
        --backend auto
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# Classes we want to mask out of the plate (handbook taxonomy)
VEHICLE_CLASSES = ("car", "truck", "bus", "motorcycle", "bicycle", "pedestrian")


@dataclass
class Instance:
    class_name: str
    bbox_xyxy: tuple[int, int, int, int]
    mask: np.ndarray  # HxW uint8 {0,255}
    score: float


# ─── Backend 1: Grounded-SAM 2 (preferred) ───────────────────────────────────
def _segment_groundedsam(frame: np.ndarray) -> list[Instance] | None:
    try:
        # Lazy import — only triggers if the user has set up Grounded-SAM 2
        from groundedsam2 import predict  # type: ignore
    except ImportError:
        return None
    # API shape varies by fork; this is a placeholder call the user wires up
    # once they've installed Grounded-SAM 2 weights.
    prompt = ". ".join(VEHICLE_CLASSES) + "."
    try:
        out = predict(frame, prompt=prompt)
        return [
            Instance(o["class_name"], tuple(o["bbox_xyxy"]), o["mask"].astype(np.uint8) * 255, float(o["score"]))
            for o in out
        ]
    except Exception as e:  # pragma: no cover — environment-specific
        print(f"[segment] Grounded-SAM 2 available but failed: {e}", file=sys.stderr)
        return None


# ─── Backend 2: Ultralytics YOLO-seg (widely available) ──────────────────────
_YOLO_CLASS_MAP = {
    "car": "car",
    "truck": "truck",
    "bus": "bus",
    "motorcycle": "motorcycle",
    "bicycle": "bicycle",
    "person": "pedestrian",
}


def _segment_yolo(frame: np.ndarray, weights: str) -> list[Instance] | None:
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        return None
    try:
        model = _segment_yolo._model  # type: ignore[attr-defined]
    except AttributeError:
        model = YOLO(weights)
        _segment_yolo._model = model  # type: ignore[attr-defined]

    result = model.predict(frame, verbose=False)[0]
    if result.masks is None:
        return []
    h, w = frame.shape[:2]
    names = result.names
    instances: list[Instance] = []
    for mask, box in zip(result.masks.data.cpu().numpy(), result.boxes):
        raw_cls = names[int(box.cls.item())]
        mapped = _YOLO_CLASS_MAP.get(raw_cls)
        if mapped is None:
            continue
        m = (mask > 0.5).astype(np.uint8) * 255
        if m.shape != (h, w):
            m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
        x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
        instances.append(Instance(mapped, (x1, y1, x2, y2), m, float(box.conf.item())))
    return instances


# ─── Backend 3: zero-dep fallback (motion-gated HOG) ─────────────────────────
# Good enough to produce *some* mask so the pipeline smoke-tests end-to-end
# even when no ML stack is installed. NOT meant for training.
def _segment_hog(frame: np.ndarray) -> list[Instance]:
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    rects, weights = hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
    h, w = frame.shape[:2]
    out: list[Instance] = []
    for (x, y, bw, bh), score in zip(rects, weights):
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[y:y + bh, x:x + bw] = 255
        out.append(Instance("pedestrian", (x, y, x + bw, y + bh), mask, float(score)))
    return out


def segment_frame(frame: np.ndarray, backend: str, yolo_weights: str) -> tuple[list[Instance], str]:
    if backend in ("auto", "groundedsam"):
        got = _segment_groundedsam(frame)
        if got is not None:
            return got, "groundedsam"
        if backend == "groundedsam":
            raise RuntimeError("Grounded-SAM 2 backend requested but not available")

    if backend in ("auto", "yolo"):
        got = _segment_yolo(frame, yolo_weights)
        if got is not None:
            return got, "yolo"
        if backend == "yolo":
            raise RuntimeError("YOLO-seg backend requested but ultralytics not installed")

    # Fallback — always succeeds
    return _segment_hog(frame), "hog"


# ─── Plate inpainting ────────────────────────────────────────────────────────
def _inpaint_lama(frame: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    """Run LaMa if the CLI / library is available."""
    try:
        from simple_lama_inpainting import SimpleLama  # type: ignore
    except ImportError:
        return None
    try:
        from PIL import Image  # type: ignore
    except ImportError:  # pragma: no cover
        return None
    lama = SimpleLama()
    pil_frame = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    pil_mask = Image.fromarray(mask)
    out = lama(pil_frame, pil_mask)
    return cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)


def _inpaint_cv2(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Cheap fallback — OpenCV Telea. Not photorealistic but deterministic."""
    return cv2.inpaint(frame, mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)


def build_plate(frames_and_masks: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """Temporal-median plate: for each pixel, take the median across frames
    ignoring positions that are under a mask. This produces a clean background
    even without LaMa, provided you have enough frames of the same scene."""
    if not frames_and_masks:
        raise ValueError("need at least one frame to build a plate")
    h, w = frames_and_masks[0][0].shape[:2]
    stack = np.zeros((len(frames_and_masks), h, w, 3), dtype=np.uint8)
    valid = np.zeros((len(frames_and_masks), h, w), dtype=bool)
    for i, (frame, mask) in enumerate(frames_and_masks):
        stack[i] = frame
        valid[i] = mask == 0  # True where background is visible
    # Per-pixel median of visible samples
    plate = np.zeros((h, w, 3), dtype=np.uint8)
    for c in range(3):
        ch = stack[..., c]
        masked = np.where(valid, ch, np.nan).astype(np.float32)
        med = np.nanmedian(masked, axis=0)
        # Fallback to plain median where the mask was everywhere
        fallback = np.median(ch, axis=0)
        med = np.where(np.isnan(med), fallback, med)
        plate[..., c] = np.clip(med, 0, 255).astype(np.uint8)
    return plate


# ─── Orchestration ───────────────────────────────────────────────────────────
def process(
    frames_dir: Path,
    out_segments: Path,
    out_crops: Path,
    out_plates: Path,
    backend: str,
    yolo_weights: str,
    plate_frames: int,
) -> dict[str, Any]:
    index_path = frames_dir / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"missing {index_path} — run 01_extract_wadisaqra_frames.py first")
    index = json.loads(index_path.read_text())

    out_segments.mkdir(parents=True, exist_ok=True)
    out_crops.mkdir(parents=True, exist_ok=True)
    out_plates.mkdir(parents=True, exist_ok=True)

    # Per-frame segmentation + crop dump, collect frames for plate
    plate_stack: list[tuple[np.ndarray, np.ndarray]] = []
    per_frame_summary = []
    backend_used: str | None = None
    for fr in index["frames"]:
        img_path = Path(fr["path"])
        if not img_path.is_absolute():
            img_path = frames_dir.parents[1] / fr["path"] if fr["path"].startswith("data/") else frames_dir / img_path.name
        if not img_path.exists():
            # Fall back to filename-only inside frames_dir
            img_path = frames_dir / Path(fr["path"]).name
        frame = cv2.imread(str(img_path))
        if frame is None:
            print(f"[segment] skipping unreadable frame {img_path}", file=sys.stderr)
            continue

        instances, used = segment_frame(frame, backend, yolo_weights)
        backend_used = used

        # Union mask for plate
        union = np.zeros(frame.shape[:2], dtype=np.uint8)
        for inst in instances:
            union = np.maximum(union, inst.mask)
        if len(plate_stack) < plate_frames:
            plate_stack.append((frame, union))

        # Per-frame COCO-lite JSON
        anns = []
        for j, inst in enumerate(instances):
            # Save crop with alpha
            x1, y1, x2, y2 = inst.bbox_xyxy
            crop_rgb = frame[y1:y2, x1:x2]
            crop_mask = inst.mask[y1:y2, x1:x2]
            if crop_rgb.size == 0:
                continue
            crop_rgba = cv2.merge([crop_rgb, crop_mask])
            crop_name = f"{img_path.stem}_{j:03d}_{inst.class_name}.png"
            cv2.imwrite(str(out_crops / crop_name), crop_rgba)
            anns.append({
                "class_name": inst.class_name,
                "bbox_xyxy": [int(v) for v in inst.bbox_xyxy],
                "score": round(inst.score, 4),
                "crop": crop_name,
                "area_px": int((inst.mask > 0).sum()),
            })
        (out_segments / f"{img_path.stem}.json").write_text(json.dumps({
            "frame": img_path.name,
            "frame_idx": fr["frame_idx"],
            "backend": used,
            "annotations": anns,
        }, indent=2))
        per_frame_summary.append({"frame": img_path.name, "n": len(anns)})

    # Build plate
    plate_path = out_plates / "wadisaqra_plate.jpg"
    if plate_stack:
        plate = build_plate(plate_stack)
        # Optional LaMa polish on a concat union mask for residual artefacts
        lama_out = _inpaint_lama(plate_stack[0][0], plate_stack[0][1])
        if lama_out is not None:
            # Use LaMa output as an additional sample, then median
            plate_stack.append((lama_out, np.zeros_like(plate_stack[0][1])))
            plate = build_plate(plate_stack)
        cv2.imwrite(str(plate_path), plate, [cv2.IMWRITE_JPEG_QUALITY, 95])

    summary = {
        "frames_in": len(index["frames"]),
        "frames_segmented": len(per_frame_summary),
        "backend": backend_used,
        "plate": str(plate_path) if plate_stack else None,
        "per_frame": per_frame_summary[:10],  # preview only
    }
    (out_segments / "_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[segment] backend={backend_used}  frames={len(per_frame_summary)}  plate={'yes' if plate_stack else 'no'}",
          file=sys.stderr)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--frames-dir", type=Path, default=Path("data/research/frames"))
    p.add_argument("--out-segments", type=Path, default=Path("data/research/segments"))
    p.add_argument("--out-crops", type=Path, default=Path("data/research/crops"))
    p.add_argument("--out-plates", type=Path, default=Path("data/research/plates"))
    p.add_argument("--backend", choices=["auto", "groundedsam", "yolo", "hog"], default="auto")
    p.add_argument("--yolo-weights", default="yolo11n-seg.pt",
                   help="Ultralytics weights name or path (downloaded on first use)")
    p.add_argument("--plate-frames", type=int, default=60,
                   help="Number of frames to use when building the background plate")
    args = p.parse_args(argv)

    process(
        args.frames_dir,
        args.out_segments,
        args.out_crops,
        args.out_plates,
        args.backend,
        args.yolo_weights,
        args.plate_frames,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
