# Phase 1 — Traffic Data Sandbox

**Purpose:** provide every downstream module (incident detection, forecasting, dashboard) with realistic simulated feeds and datasets, so Phase 2 / Phase 3 can be built and validated against a stable, reproducible baseline.

> Handbook §6: *"If this phase is weak, all downstream modules will be weak."*

## What the sandbox produces

| Artifact | Path | Produced by | Handbook § |
|---|---|---|---|
| Live-like RTSP stream | `rtsp://localhost:8554/site1` @ 1920×1080 / 10 FPS / H.264 | MediaMTX + `publish_loop.sh` | §6.1 |
| Historical video pack | `data/historical/YYYY-MM-DD/clip-*.mp4` (14 days) | `ingest.clip_cutter` | §6.2 |
| Detector counts dataset | `data/detector_counts/counts_YYYY-MM-DD.parquet` (22 × 96 × 14) | `synth.detector_counts` | §6.3 |
| Signal timing log | `data/signal_logs/signal_YYYY-MM-DD.ndjson` | `synth.signal_logs` | §6.4 |
| Intersection metadata | `data/metadata/site1.json` (from stub) | `metadata.schema` | §6.5 |
| Annotation pack | `data/annotations/{coco,yolo,events}/` | CVAT + `annotation.seed_cvat` | §6.6 |
| Data dictionary | `phase1-sandbox/data_dictionary.md` | hand-written | §6 deliverables |
| Methodology note | `phase1-sandbox/methodology.md` | hand-written | §6 deliverables |

## How the sandbox is built — end to end

**v1 source-of-truth is Google Veo 3 generative video** (see `configs/veo3_prompts.md`). YouTube and other real-footage sources remain operational as fallbacks — see `methodology.md` for the rationale.

```
1. VEO 3 GENERATION ─────► data/raw/veo3/*.mp4                 (you generate externally)
   (OR yt-dlp fallback) ─► data/raw/youtube/*.mp4              (make fetch-videos)
2. NORMALIZE    ─────────► data/normalized/*.mp4               (ffmpeg → 1080p/10fps/H.264)
3. HISTORICAL PACK ──────► data/historical/YYYY-MM-DD/*.mp4    (ffmpeg -c copy cut)
4. RTSP SIM     ─────────► rtsp://localhost:8554/site1         (MediaMTX + ffmpeg loop)
5. SYNTH COUNTS ─────────► data/detector_counts/*.parquet      (numpy + pyarrow)
6. SYNTH SIGNALS ────────► data/signal_logs/*.ndjson           (stdlib)
7. METADATA     ─────────► data/metadata/site1.json            (stub → filled by user)
8. ANNOTATION   ─────────► CVAT at :8080 → data/annotations/*  (CVAT)
9. VERIFY       ─────────► make sandbox-verify                 (pytest)
```

**Quickest path with Veo 3 footage:**

```bash
# Drop generated clips into data/raw/veo3/
cp my-veo3-clips/*.mp4 data/raw/veo3/

# One-shot normalize + historical pack
make veo3-ingest

# Go live
make sandbox-up stream-check synth-all validate-metadata sandbox-verify
```

### Walk-through

**Step 1 — YouTube research (you).** Edit `configs/sources.yml` with 4–8 stable, wide-angle traffic CCTV URLs (see file comments for the shopping list).

**Step 2 — Fetch (`make fetch-videos`).** `yt-dlp` pulls each URL at ≤1080p MP4 into `data/raw/youtube/`. Idempotent: already-downloaded files are skipped.

**Step 3 — Normalize (`make normalize-videos`).** Every raw file is re-encoded through a fixed profile: scale-to-fit 1920×1080 with black-bar padding, 10 FPS, H.264 CRF 23, audio stripped, `+faststart` for network playback. This guarantees the RTSP output and every historical clip hit the exact ingestion assumptions the handbook specifies (§6.1).

**Step 4 — Historical pack (`make historical-pack`).** For each of 14 days, we cut three 3-minute clips (AM / midday / PM window labels) from the normalized pool. `ffmpeg -c copy` means no re-encode cost. Reproducible via the `--seed` flag. Real 14-day footage would be ideal but is rarely available, so this sampling approach is documented explicitly in `methodology.md`.

**Step 5 — RTSP simulator (`make stream-up`).** `docker compose up -d mediamtx` starts the MediaMTX container with our `mediamtx.yml` config (RTSP only, TCP only, localhost-bound, no auth needed inside the loopback). `scripts/publish_loop.sh` then launches a background `ffmpeg -re -stream_loop -1 ... -f rtsp rtsp://localhost:8554/site1` so the first normalized clip loops forever — indistinguishable from a live camera to downstream code. `healthcheck.py` uses `ffprobe` to verify resolution + FPS + codec and emits a one-line JSON report.

**Step 6 — Detector counts (`make synth-counts`).** For each detector (22 total, matching handbook §6.3), we build a per-minute arrival-rate curve from three Gaussian peaks (AM, midday, PM) scaled by weekday/weekend multiplier and a per-detector baseline. Poisson draws per minute, integrated into 96 × 15-minute bins, stored as Parquet with a strict Arrow schema. Seed-deterministic — same seed, byte-identical file.

**Step 7 — Signal timing (`make synth-signals`).** A 4-phase NEMA-style plan (phases 2-6-4-8) runs continuously for 24 hours. Each phase transition emits a `GREEN_ON / YELLOW_ON / RED_ON` event. Cycle lengths are jittered ±4s to resemble a semi-actuated controller. Nominal cycle is 102 s, within handbook §6.4 (90–120s).

**Step 8 — Metadata (`make validate-metadata`).** `intersection_schema.json` is a JSON Schema draft 2020-12 describing camera position/FOV, lane configuration, stop-lines, and monitoring zones (queue spillback polygons). `site1.example.json` is a filled stub the user edits when the actual intersection is chosen; the validator is a hard precondition for Phase 2.

**Step 9 — Annotation (`make annotation-up`).** Starts CVAT via docker-compose profile `annotation`. `seed_cvat.py` creates initial tasks from the historical pack with the taxonomy in `annotation/taxonomy.yml` (6 object classes + 6 event-window tags from handbook §6.6). Annotator exports to `data/annotations/{coco,yolo,events}` as COCO-JSON, YOLO-txt, and event-window CSV.

**Step 10 — Verify (`make sandbox-verify`).** pytest runs 7 test files: schema validity, round-trips, determinism, weekday/weekend shape, AM/PM peak placement, signal format/alternation, and — optionally — a live RTSP probe.

## Design principles

- **Every step is reproducible from config alone.** No manual clicks or one-off scripts. Re-running with the same seed yields byte-identical outputs.
- **Every dataset has a typed schema.** Parquet → Arrow schema. NDJSON → explicit key set. Metadata → JSON Schema.
- **Idempotent.** Re-running `make X` is safe; artifacts that already exist are skipped.
- **Read-only toward external systems.** No writes anywhere except `data/` and `/tmp/traffic-intel-ffmpeg.{pid,log}`.
- **Small blast radius.** All containers bind to 127.0.0.1 only. No secrets in git.

## Deliverables checklist (handbook §6)

- [x] Traffic data sandbox package (this directory)
- [x] Live-like RTSP video stream simulation
- [x] Historical video training pack pipeline
- [x] Traffic detector dataset (22 detectors × 15-min × configurable days)
- [x] Signal timing log dataset
- [x] Intersection metadata schema + example instance
- [x] Annotation & labeling package (CVAT + taxonomy)
- [x] Data dictionary (`data_dictionary.md`)
- [x] Methodology note (`methodology.md`)
