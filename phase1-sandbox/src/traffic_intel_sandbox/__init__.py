"""Traffic-Intel Phase 1 Sandbox package.

Modules:
    ingest       — YouTube fetch, normalize, clip cutter         (C1–C3)
    rtsp_sim     — MediaMTX publish loop + healthcheck           (C4–C6)
    synth        — detector counts + signal timing generators    (C7–C9)
    metadata     — intersection JSON Schema + validator          (C10–C11)
    annotation   — CVAT seeder + taxonomy                        (C12–C13)

All modules expose a `main()` entry point wired through pyproject.toml
scripts table; run any of them with either:

    python -m traffic_intel_sandbox.<module>.<cmd> ...
    sandbox-<cmd> ...   # after `pip install -e .`
"""

__version__ = "0.1.0"
