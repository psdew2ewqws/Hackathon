from __future__ import annotations

import logging
import os
from pathlib import Path

from .base import DetectorBackend
from .tracking import ByteTrackWrapper

LOG = logging.getLogger(__name__)

# phase3-fullstack/src/traffic_intel_detector/factory.py
#  parents[0]=traffic_intel_detector  [1]=src  [2]=phase3-fullstack  [3]=traffic-intel
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_YOLO_WEIGHTS = REPO_ROOT / "yolo26n.pt"


def build_detector(
    *,
    backend: str | None = None,
    weights: str | Path | None = None,
) -> DetectorBackend:
    """Build a DetectorBackend instance from env (or explicit overrides)."""
    backend = (backend or os.environ.get("DETECTOR_BACKEND", "rfdetr")).lower()
    device = os.environ.get("DETECTOR_DEVICE", "cuda")
    fp16 = os.environ.get("DETECTOR_FP16", "1") == "1"

    if backend == "ultralytics":
        from .ultralytics_backend import UltralyticsBackend

        weights = weights or os.environ.get("YOLO_WEIGHTS") or str(DEFAULT_YOLO_WEIGHTS)
        return UltralyticsBackend(weights=weights, device=device, fp16=fp16)

    if backend == "rfdetr":
        from .rfdetr_backend import RFDetrBackend

        size = os.environ.get("RFDETR_SIZE", "base")
        if size not in ("base", "large"):
            raise ValueError(f"RFDETR_SIZE={size!r}; expected base|large")
        optimize = os.environ.get("RFDETR_OPTIMIZE", "0") == "1"
        return RFDetrBackend(  # type: ignore[arg-type]
            size=size, device=device, fp16=fp16, optimize=optimize
        )

    raise ValueError(f"unknown DETECTOR_BACKEND={backend!r}; expected ultralytics|rfdetr")


def build_tracker(*, frame_rate: int | None = None) -> ByteTrackWrapper:
    fr = frame_rate or int(os.environ.get("TRACKER_FRAME_RATE", "10"))
    return ByteTrackWrapper(frame_rate=fr)
