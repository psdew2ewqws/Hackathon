"""Camera motion tracker — keeps our zone overlays glued to the road even
when the RTSP feed pans, zooms, or tilts.

The algorithm is the textbook one:
    1. At startup we capture one **reference frame** and extract ORB
       keypoints + descriptors.
    2. Each tick we do the same on the current frame, match descriptors
       against the reference, and solve for a 3×3 **homography H** via
       RANSAC.
    3. Every polygon / line defined in ``forecast_site.json`` lives in the
       reference frame's pixel space; we apply H to each polygon with
       ``cv2.perspectiveTransform`` before drawing or counting.

Why ORB + BF + RANSAC:
    * ORB is fast (no GPU), rotation-invariant, and free (BSD).
    * BFMatcher with crossCheck gives robust matches without KNN ratio
      tuning.
    * RANSAC in ``findHomography`` rejects outliers from moving cars.

Failure modes are handled gracefully — if we can't find enough matches
(e.g. sudden scene change, heavy motion blur) we re-use the most recent
smoothed H. A new good match overrides it.

No GPU / no extra deps — just the OpenCV that ultralytics already pulls
in.
"""

from __future__ import annotations

import numpy as np
import cv2


class CameraTracker:
    def __init__(
        self,
        n_features:     int   = 1000,
        min_matches:    int   = 15,
        smoothing:      float = 0.35,
        update_every:   int   = 1,
        ransac_thresh:  float = 5.0,
        bottom_mask_frac: float = 0.15,
        top_mask_frac:    float = 0.05,
    ) -> None:
        self.orb = cv2.ORB_create(nfeatures=n_features)
        self.bf  = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.min_matches  = min_matches
        self.alpha        = smoothing
        self.update_every = update_every
        self.ransac_thresh = ransac_thresh
        self.bottom_mask_frac = bottom_mask_frac
        self.top_mask_frac    = top_mask_frac

        self.ref_kp: list | None = None
        self.ref_des: np.ndarray | None = None
        self.ref_shape: tuple[int, int] | None = None
        self.smoothed_H = np.eye(3, dtype=np.float64)
        self._tick = 0
        self._last_good: np.ndarray = np.eye(3, dtype=np.float64)
        self._last_match_count = 0
        self.stats: dict = {
            "frames_updated":   0,
            "frames_skipped":   0,
            "last_match_count": 0,
            "ref_set":          False,
        }

    # ── Helpers ────────────────────────────────────────────────────────
    def _mask(self, h: int, w: int) -> np.ndarray:
        """Exclude top/bottom strips that typically carry sky or
        subtitle/logo overlays (bad for ORB)."""
        mask = np.full((h, w), 255, dtype=np.uint8)
        bot = int(h * (1.0 - self.bottom_mask_frac))
        top = int(h * self.top_mask_frac)
        mask[bot:, :] = 0
        mask[:top, :] = 0
        return mask

    def set_reference(self, frame: np.ndarray) -> None:
        """Designate this frame as the reference. All zone coordinates are
        interpreted in this frame's pixel space."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        mask = self._mask(h, w)
        kp, des = self.orb.detectAndCompute(gray, mask)
        if des is None or len(kp) < self.min_matches:
            return
        self.ref_kp = kp
        self.ref_des = des
        self.ref_shape = (h, w)
        self.smoothed_H = np.eye(3, dtype=np.float64)
        self._last_good = np.eye(3, dtype=np.float64)
        self.stats["ref_set"] = True

    def update(self, frame: np.ndarray) -> np.ndarray:
        """Update the running homography using this frame. Returns the
        current (smoothed) H. Callers can call this every frame; internally
        we skip work according to ``update_every`` to save CPU."""
        self._tick += 1
        if self.ref_kp is None:
            self.set_reference(frame)
            return self.smoothed_H
        if self._tick % self.update_every != 0:
            self.stats["frames_skipped"] += 1
            return self.smoothed_H

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        mask = self._mask(h, w)
        kp, des = self.orb.detectAndCompute(gray, mask)
        if des is None or len(kp) < self.min_matches or self.ref_des is None:
            self.stats["frames_skipped"] += 1
            return self.smoothed_H

        try:
            matches = self.bf.match(self.ref_des, des)
        except cv2.error:
            self.stats["frames_skipped"] += 1
            return self.smoothed_H
        matches = sorted(matches, key=lambda m: m.distance)[:300]
        self.stats["last_match_count"] = len(matches)
        self._last_match_count = len(matches)
        if len(matches) < self.min_matches:
            self.stats["frames_skipped"] += 1
            return self.smoothed_H

        src = np.float32([self.ref_kp[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst = np.float32([kp[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        H, _inliers = cv2.findHomography(src, dst, cv2.RANSAC, self.ransac_thresh)
        if H is None:
            self.stats["frames_skipped"] += 1
            return self.smoothed_H

        self._last_good = H.astype(np.float64)
        self.smoothed_H = (self.alpha * H + (1 - self.alpha) * self.smoothed_H).astype(np.float64)
        self.stats["frames_updated"] += 1
        return self.smoothed_H

    # ── Apply H to geometry ────────────────────────────────────────────
    def transform_polygon(self, polygon: np.ndarray) -> np.ndarray:
        """Warp a polygon (N, 2) through the current homography."""
        if polygon is None or polygon.ndim != 2 or polygon.shape[0] < 2:
            return polygon
        pts = polygon.astype(np.float32).reshape(-1, 1, 2)
        warped = cv2.perspectiveTransform(pts, self.smoothed_H.astype(np.float32))
        return warped.reshape(-1, 2).astype(np.int32)

    def transform_point(self, x: float, y: float) -> tuple[int, int]:
        pts = np.float32([[[x, y]]])
        warped = cv2.perspectiveTransform(pts, self.smoothed_H.astype(np.float32))
        return int(warped[0, 0, 0]), int(warped[0, 0, 1])

    def transform_line(self, p0: tuple[float, float], p1: tuple[float, float]) -> tuple[tuple[int, int], tuple[int, int]]:
        return self.transform_point(*p0), self.transform_point(*p1)
