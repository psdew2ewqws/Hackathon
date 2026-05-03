from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import supervision as sv

# 80-class COCO indexing as used by Ultralytics: car, motorcycle, bus, truck.
YOLO_VEHICLE_CLASSES = (2, 3, 5, 7)

LOG = logging.getLogger(__name__)


class UltralyticsBackend:
    name = "ultralytics"

    def __init__(
        self,
        weights: str | Path,
        *,
        device: str = "cuda",
        fp16: bool = True,
        imgsz: int = 960,
        conf: float = 0.35,
        iou: float = 0.5,
    ) -> None:
        from ultralytics import YOLO

        self._weights = str(weights)
        self._device = device
        self._fp16 = fp16
        self._imgsz = imgsz
        self._conf = conf
        self._iou = iou
        self._model = YOLO(self._weights)
        LOG.info(
            "ultralytics backend ready weights=%s device=%s fp16=%s imgsz=%d",
            self._weights, self._device, self._fp16, self._imgsz,
        )

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections:
        results = self._model.predict(
            frame_bgr,
            classes=list(YOLO_VEHICLE_CLASSES),
            imgsz=self._imgsz,
            conf=self._conf,
            iou=self._iou,
            device=self._device,
            half=self._fp16 and self._device != "cpu",
            verbose=False,
        )
        return sv.Detections.from_ultralytics(results[0])

    def warmup(self, frame_bgr: np.ndarray) -> None:
        for _ in range(2):
            self.detect(frame_bgr)

    def info(self) -> dict:
        return {
            "backend": self.name,
            "weights": self._weights,
            "device": self._device,
            "fp16": self._fp16,
            "imgsz": self._imgsz,
            "conf": self._conf,
            "iou": self._iou,
        }
