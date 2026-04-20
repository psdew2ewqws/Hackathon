"""Phase 2 — Crack-the-Code Feasibility Build.

Real-time detection + tracking on the Phase 1 RTSP stream using:
    • Ultralytics YOLO26 (NMS-free end-to-end detection)
    • Ultralytics built-in BoT-SORT (with ByteTrack fallback)
    • roboflow/supervision for line-crossing counters and overlays

Entry points (installed via pyproject.toml):
    phase2-detect   run detect + track, annotated video + events
    phase2-bench    micro-benchmark detection latency on a clip
"""

__version__ = "0.1.0"
