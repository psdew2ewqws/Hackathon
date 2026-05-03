from __future__ import annotations

from typing import Protocol

import numpy as np
import supervision as sv


class DetectorBackend(Protocol):
    name: str

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections: ...

    def warmup(self, frame_bgr: np.ndarray) -> None: ...

    def info(self) -> dict: ...
