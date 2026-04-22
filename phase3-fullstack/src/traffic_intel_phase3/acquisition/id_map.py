"""Detector / camera / approach identity mapping.

Loads ``configs/id_map.json`` (optional) and provides lookup helpers.  Used
when upstream source records omit approach/lane identifiers, or when we need
to map a site's detector_id to its canonical approach.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger(__name__)


@dataclass
class IdMap:
    detector_to_approach: dict[str, str] = field(default_factory=dict)
    camera_to_site: dict[str, str] = field(default_factory=dict)
    approach_aliases: dict[str, str] = field(default_factory=dict)  # e.g. "north" -> "N"

    @classmethod
    def load(cls, path: Path) -> "IdMap":
        if not path.exists():
            LOG.info("id_map not found at %s; returning empty map", path)
            return cls()
        data = json.loads(path.read_text())
        return cls(
            detector_to_approach=data.get("detector_to_approach", {}) or {},
            camera_to_site=data.get("camera_to_site", {}) or {},
            approach_aliases=data.get("approach_aliases", {}) or {},
        )

    def resolve_approach(self, detector_id: str | None = None,
                         raw_label: str | None = None) -> str | None:
        if detector_id and detector_id in self.detector_to_approach:
            return self.detector_to_approach[detector_id]
        if raw_label:
            key = raw_label.strip().lower()
            if key in self.approach_aliases:
                return self.approach_aliases[key]
            if key.upper() in ("N", "S", "E", "W"):
                return key.upper()
        return None

    def resolve_site(self, camera_id: str | None) -> str | None:
        if not camera_id:
            return None
        return self.camera_to_site.get(camera_id)
