from __future__ import annotations

import logging
from typing import Literal

import cv2
import numpy as np
import supervision as sv

# RF-DETR ships with 91-class (1-indexed) COCO labels: car, motorcycle, bus, truck.
RFDETR_VEHICLE_CLASSES = (3, 4, 6, 8)

# Canonical 91-class COCO label table. We override RF-DETR's built-in
# class_name strings with this lookup because the supervision Detections
# returned by RFDETRBase().predict() carries an 80-class label list
# indexed with 91-class IDs — every label is shifted (car→motorcycle,
# bus→train, person→bicycle). Confirmed empirically against rfdetr 1.6.5.
COCO_91_NAMES = {
    1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 5: "airplane",
    6: "bus", 7: "train", 8: "truck", 9: "boat", 10: "traffic light",
    11: "fire hydrant", 13: "stop sign", 14: "parking meter", 15: "bench",
    16: "bird", 17: "cat", 18: "dog", 19: "horse", 20: "sheep",
    21: "cow", 22: "elephant", 23: "bear", 24: "zebra", 25: "giraffe",
    27: "backpack", 28: "umbrella", 31: "handbag", 32: "tie", 33: "suitcase",
    34: "frisbee", 35: "skis", 36: "snowboard", 37: "sports ball", 38: "kite",
    39: "baseball bat", 40: "baseball glove", 41: "skateboard", 42: "surfboard",
    43: "tennis racket", 44: "bottle", 46: "wine glass", 47: "cup", 48: "fork",
    49: "knife", 50: "spoon", 51: "bowl", 52: "banana", 53: "apple",
    54: "sandwich", 55: "orange", 56: "broccoli", 57: "carrot", 58: "hot dog",
    59: "pizza", 60: "donut", 61: "cake", 62: "chair", 63: "couch",
    64: "potted plant", 65: "bed", 67: "dining table", 70: "toilet",
    72: "tv", 73: "laptop", 74: "mouse", 75: "remote", 76: "keyboard",
    77: "cell phone", 78: "microwave", 79: "oven", 80: "toaster",
    81: "sink", 82: "refrigerator", 84: "book", 85: "clock", 86: "vase",
    87: "scissors", 88: "teddy bear", 89: "hair drier", 90: "toothbrush",
}

LOG = logging.getLogger(__name__)


class RFDetrBackend:
    name = "rfdetr"

    def __init__(
        self,
        *,
        size: Literal["base", "large"] = "base",
        device: str = "cuda",
        fp16: bool = True,
        conf: float = 0.35,
        optimize: bool = False,
    ) -> None:
        # optimize_for_inference() should JIT-trace the model and speed
        # up inference, but on rfdetr 1.6.5 + RTX 3060 it does the
        # opposite: FPS crashes ~7x (9.7 -> 1.3) and VRAM doubles
        # (390 -> 1040 MiB). Off by default. Set RFDETR_OPTIMIZE=1 to
        # re-enable if a future rfdetr release fixes it.
        from rfdetr import RFDETRBase, RFDETRLarge

        cls = RFDETRBase if size == "base" else RFDETRLarge
        self._size = size
        self._device = device
        self._fp16 = fp16
        self._conf = conf
        # rfdetr places the model on cuda automatically when available; honor
        # DETECTOR_DEVICE only insofar as we report it.
        self._model = cls()
        if optimize:
            try:
                self._model.optimize_for_inference()
                LOG.info("rfdetr-%s optimized for inference", size)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("rfdetr optimize_for_inference failed: %s", exc)
        LOG.info("rfdetr backend ready size=%s conf=%.2f", size, conf)

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        det = self._model.predict(rgb, threshold=self._conf)
        if det.class_id is not None and len(det) > 0:
            mask = np.isin(det.class_id, RFDETR_VEHICLE_CLASSES)
            det = det[mask]
        # Replace rfdetr's shifted class_name strings with the canonical
        # 91-class lookup so downstream label rendering is correct.
        if det.class_id is not None and len(det) > 0:
            names = np.array(
                [COCO_91_NAMES.get(int(cid), str(int(cid))) for cid in det.class_id]
            )
            data = dict(det.data) if det.data else {}
            data["class_name"] = names
            det.data = data
        return det

    def warmup(self, frame_bgr: np.ndarray) -> None:
        for _ in range(2):
            self.detect(frame_bgr)

    def info(self) -> dict:
        return {
            "backend": self.name,
            "size": self._size,
            "device": self._device,
            "fp16": self._fp16,
            "conf": self._conf,
        }
