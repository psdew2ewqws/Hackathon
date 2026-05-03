"""Pluggable vehicle-detection backends for the traffic-intel pipeline.

Two implementations live alongside each other behind a common interface so
phase 2 and phase 3 can swap between Ultralytics YOLO and RF-DETR via the
DETECTOR_BACKEND env var. Both backends emit supervision.Detections and are
paired with a single shared external ByteTrack instance, which keeps the
detector-vs-detector comparison honest.
"""
from .base import DetectorBackend
from .factory import build_detector, build_tracker
from .tracking import ByteTrackWrapper

__all__ = ["DetectorBackend", "build_detector", "build_tracker", "ByteTrackWrapper"]
