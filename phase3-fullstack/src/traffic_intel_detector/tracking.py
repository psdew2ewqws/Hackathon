from __future__ import annotations

import numpy as np
import supervision as sv


class ByteTrackWrapper:
    """Thin wrapper around supervision.ByteTrack.

    Exists so both backends share one tracker class regardless of which
    detector they're paired with — keeps the detector-vs-detector comparison
    honest and gives us a single place to tune ByteTrack parameters.
    """

    def __init__(
        self,
        *,
        frame_rate: int = 10,
        lost_track_buffer: int = 30,
        minimum_matching_threshold: float = 0.8,
        minimum_consecutive_frames: int = 1,
    ) -> None:
        self._tracker = sv.ByteTrack(
            frame_rate=frame_rate,
            lost_track_buffer=lost_track_buffer,
            minimum_matching_threshold=minimum_matching_threshold,
            minimum_consecutive_frames=minimum_consecutive_frames,
        )

    def update(
        self,
        detections: sv.Detections,
        frame_bgr: np.ndarray | None = None,  # accepted for future-proofing
    ) -> sv.Detections:
        return self._tracker.update_with_detections(detections)

    def reset(self) -> None:
        self._tracker.reset()
