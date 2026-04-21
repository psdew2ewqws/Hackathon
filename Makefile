# ─── Traffic-Intel Makefile ──────────────────────────────────────────────────
# Single entry-point for the Phase 1 sandbox workflow.
# All targets are idempotent unless noted otherwise.

SHELL      := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY           ?= python3
VENV         ?= .venv
VENV_PY      := $(VENV)/bin/python
VENV_PIP     := $(VENV)/bin/pip
PYTEST       := $(VENV)/bin/pytest

DATA_DIR             ?= data
# Default ingest source is youtube/; override to `data/raw/veo3` (or any dir)
# for generative-model footage:
#   make normalize-videos RAW_VIDEO_DIR=data/raw/veo3
RAW_VIDEO_DIR        ?= $(DATA_DIR)/raw/youtube
VEO3_VIDEO_DIR       ?= $(DATA_DIR)/raw/veo3
NORMALIZED_VIDEO_DIR ?= $(DATA_DIR)/normalized
HISTORICAL_DIR       ?= $(DATA_DIR)/historical
COUNTS_DIR           ?= $(DATA_DIR)/detector_counts
SIGNALS_DIR          ?= $(DATA_DIR)/signal_logs
METADATA_DIR         ?= $(DATA_DIR)/metadata

SANDBOX_DAYS         ?= 14
SOURCES_YAML         ?= phase1-sandbox/configs/sources.yml
PROFILES_YAML        ?= phase1-sandbox/configs/profiles.yml
PHASE_PLAN_YAML      ?= phase1-sandbox/configs/phase_plan.yml
SITE_METADATA        ?= phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json
RTSP_URL             ?= rtsp://localhost:8554/site1

# ─── Help ────────────────────────────────────────────────────────────────────
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ─── Setup ───────────────────────────────────────────────────────────────────
setup: $(VENV) ## Create venv + install Python deps
$(VENV):
	$(PY) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -e '.[dev]'

docker-pull: ## Pre-pull required docker images
	docker pull bluenviron/mediamtx:1.16.0
	docker pull postgres:16-alpine

# ─── Ingest ──────────────────────────────────────────────────────────────────
fetch-videos: setup ## Download videos listed in sources.yml
	$(VENV_PY) -m traffic_intel_sandbox.ingest.youtube_fetch \
		--sources $(SOURCES_YAML) --out $(RAW_VIDEO_DIR)

normalize-videos: setup ## Re-encode raw videos to 1080p/10fps/H.264
	$(VENV_PY) -m traffic_intel_sandbox.ingest.normalize \
		--in-dir $(RAW_VIDEO_DIR) --out-dir $(NORMALIZED_VIDEO_DIR)

historical-pack: setup ## Slice into $(SANDBOX_DAYS)-day historical structure
	$(VENV_PY) -m traffic_intel_sandbox.ingest.clip_cutter \
		--in-dir $(NORMALIZED_VIDEO_DIR) --out-dir $(HISTORICAL_DIR) --days $(SANDBOX_DAYS)

# ─── Veo3 convenience chain ──────────────────────────────────────────────────
# End-to-end: normalize Veo3 generated MP4s → historical pack, one command.
veo3-ingest: setup ## Normalize + pack Veo3 videos from data/raw/veo3/
	$(VENV_PY) -m traffic_intel_sandbox.ingest.normalize \
		--in-dir $(VEO3_VIDEO_DIR) --out-dir $(NORMALIZED_VIDEO_DIR)
	$(VENV_PY) -m traffic_intel_sandbox.ingest.clip_cutter \
		--in-dir $(NORMALIZED_VIDEO_DIR) --out-dir $(HISTORICAL_DIR) --days $(SANDBOX_DAYS)

# ─── RTSP stream ─────────────────────────────────────────────────────────────
stream-up: ## Start MediaMTX + publish first normalized clip in a loop
	docker compose up -d mediamtx
	bash phase1-sandbox/scripts/publish_loop.sh $(NORMALIZED_VIDEO_DIR) $(RTSP_URL)

stream-check: setup ## Verify RTSP resolution + FPS + codec
	$(VENV_PY) -m traffic_intel_sandbox.rtsp_sim.healthcheck --url $(RTSP_URL)

stream-down: ## Stop publisher + mediamtx
	-pkill -f "ffmpeg.*$(RTSP_URL)" || true
	docker compose stop mediamtx

# ─── Synthetic data ──────────────────────────────────────────────────────────
synth-counts: setup ## Generate detector counts parquet ($(SANDBOX_DAYS) days)
	$(VENV_PY) -m traffic_intel_sandbox.synth.detector_counts \
		--profiles $(PROFILES_YAML) --out-dir $(COUNTS_DIR) --days $(SANDBOX_DAYS)

synth-signals: setup ## Generate signal timing ndjson ($(SANDBOX_DAYS) days)
	$(VENV_PY) -m traffic_intel_sandbox.synth.signal_logs \
		--phase-plan $(PHASE_PLAN_YAML) --out-dir $(SIGNALS_DIR) --days $(SANDBOX_DAYS)

synth-all: synth-counts synth-signals ## Counts + signals together

# ─── Metadata ────────────────────────────────────────────────────────────────
validate-metadata: setup ## JSON-schema-validate site metadata
	$(VENV_PY) -m traffic_intel_sandbox.metadata.validator --site $(SITE_METADATA)

# ─── Annotation (CVAT) ───────────────────────────────────────────────────────
annotation-up: ## Start CVAT stack (profile=annotation)
	docker compose --profile annotation up -d
	@echo ""
	@echo "CVAT starting at http://localhost:8080"
	@echo "Create superuser (first run only):"
	@echo "  docker exec -it traffic-intel-cvat-server bash -ic 'python3 ~/manage.py createsuperuser'"

annotation-seed: setup ## Create CVAT tasks from historical clips
	$(VENV_PY) -m traffic_intel_sandbox.annotation.seed_cvat \
		--clips-dir $(HISTORICAL_DIR) --taxonomy phase1-sandbox/src/traffic_intel_sandbox/annotation/taxonomy.yml

annotation-down: ## Stop CVAT stack
	docker compose --profile annotation stop

# ─── Sandbox lifecycle ───────────────────────────────────────────────────────
sandbox-up: stream-up ## Bring sandbox online (stream + core services)

sandbox-verify: setup ## Run full pytest verification suite
	$(PYTEST) phase1-sandbox/tests/

viewer: setup ## Open the tiny sandbox preview dashboard at :8000
	$(VENV_PY) -m traffic_intel_sandbox.viewer

# ─── Phase 2: YOLO26 detect + track ──────────────────────────────────────────
PHASE2_MODEL   ?= yolo26n.pt
PHASE2_TRACKER ?= botsort.yaml
PHASE2_SECONDS ?= 30
PHASE2_EVENTS  ?= data/events/phase2.ndjson
PHASE2_VIDEO   ?= data/annotated/phase2.mp4

phase2-detect: setup ## Run YOLO26 + BoT-SORT on live RTSP, save annotated video + events
	mkdir -p $(dir $(PHASE2_EVENTS)) $(dir $(PHASE2_VIDEO))
	$(VENV_PY) -m traffic_intel_phase2.detect_track \
		--source $(RTSP_URL) \
		--model  $(PHASE2_MODEL) \
		--tracker $(PHASE2_TRACKER) \
		--events-out $(PHASE2_EVENTS) \
		--video-out  $(PHASE2_VIDEO) \
		--max-frames $$(( $(PHASE2_SECONDS) * 10 ))

PHASE2_MJPEG_PORT ?= 8081
phase2-live: setup ## Run detection unbounded, stream annotated MJPEG on :8081
	mkdir -p $(dir $(PHASE2_EVENTS))
	@echo "→ Open  http://localhost:$(PHASE2_MJPEG_PORT)/stream.mjpeg  (or the viewer at :8000)"
	$(VENV_PY) -m traffic_intel_phase2.detect_track \
		--source $(RTSP_URL) \
		--model  $(PHASE2_MODEL) \
		--tracker $(PHASE2_TRACKER) \
		--events-out $(PHASE2_EVENTS) \
		--mjpeg-port $(PHASE2_MJPEG_PORT)

phase2-live-bg: setup ## Same as phase2-live but in background (make phase2-live-down to stop)
	mkdir -p $(dir $(PHASE2_EVENTS))
	@if [ -f /tmp/traffic-intel-phase2.pid ] && kill -0 $$(cat /tmp/traffic-intel-phase2.pid) 2>/dev/null; then \
	    kill $$(cat /tmp/traffic-intel-phase2.pid) 2>/dev/null || true; sleep 1; fi
	@nohup $(VENV_PY) -m traffic_intel_phase2.detect_track \
		--source $(RTSP_URL) --model $(PHASE2_MODEL) --tracker $(PHASE2_TRACKER) \
		--events-out $(PHASE2_EVENTS) --mjpeg-port $(PHASE2_MJPEG_PORT) \
		> /tmp/traffic-intel-phase2.log 2>&1 & echo $$! > /tmp/traffic-intel-phase2.pid
	@sleep 2
	@echo "phase2-live pid $$(cat /tmp/traffic-intel-phase2.pid)  log=/tmp/traffic-intel-phase2.log"
	@echo "→ Open http://localhost:$(PHASE2_MJPEG_PORT)/stream.mjpeg  (or the viewer at :8000)"

phase2-live-down: ## Stop background phase2-live
	@if [ -f /tmp/traffic-intel-phase2.pid ] && kill -0 $$(cat /tmp/traffic-intel-phase2.pid) 2>/dev/null; then \
	    kill $$(cat /tmp/traffic-intel-phase2.pid) && echo "stopped"; else echo "not running"; fi
	@rm -f /tmp/traffic-intel-phase2.pid

# ─── Phase 1 §6.6 closure: automated event classification ───────────────────
PHASE2_NORMALIZED_DIR ?= data/normalized/events

phase2-classify: ## Rule-based event classifier; updates data/labels/clips_manifest.json
	$(VENV_PY) -m traffic_intel_phase2.classifier \
		--batch --update-manifest \
		--normalized-dir $(PHASE2_NORMALIZED_DIR)

sandbox-down: stream-down annotation-down ## Stop all sandbox services

sandbox-package: ## Tar data + docs into dist/sandbox-v1.tar.zst (needs zstd)
	mkdir -p dist
	tar --zstd -cf dist/sandbox-v1.tar.zst \
		data/detector_counts data/signal_logs data/metadata \
		phase1-sandbox/data_dictionary.md phase1-sandbox/methodology.md

# ─── Research: sim-to-real prototypes (phase1-sandbox/experiments) ──────────
RESEARCH_DIR      ?= data/research
RESEARCH_VIDEO    ?= $(RAW_VIDEO_DIR)/amman-wadi-saqra-tour.mp4
RESEARCH_DATE     ?= $(shell date -u +%Y-%m-%d)
RESEARCH_SEED     ?= 42
RESEARCH_SECONDS  ?= 30
RESEARCH_PER_CLASS ?= 10
RESEARCH_EVENT_SECONDS ?= 15
EXPERIMENTS       := phase1-sandbox/experiments

research-frames: setup ## Stage 01: extract high-quality keyframes from Wadi Saqra video
	$(VENV_PY) $(EXPERIMENTS)/01_extract_wadisaqra_frames.py \
		--video $(RESEARCH_VIDEO) \
		--out-dir $(RESEARCH_DIR)/frames \
		--seed $(RESEARCH_SEED)

research-segment: setup ## Stage 02: segment vehicles + build clean background plate
	$(VENV_PY) $(EXPERIMENTS)/02_segment_and_inpaint.py \
		--frames-dir $(RESEARCH_DIR)/frames \
		--out-segments $(RESEARCH_DIR)/segments \
		--out-crops    $(RESEARCH_DIR)/crops \
		--out-plates   $(RESEARCH_DIR)/plates \
		--backend auto

research-sumo: setup ## Stage 03: coupled counts + signals + trajectories (real SUMO by default)
	$(VENV_PY) $(EXPERIMENTS)/03_sumo_scenario.py \
		--profiles $(PROFILES_YAML) \
		--phase-plan $(PHASE_PLAN_YAML) \
		--site-meta $(SITE_METADATA) \
		--out-dir $(RESEARCH_DIR)/sumo \
		--date $(RESEARCH_DATE) \
		--seed $(RESEARCH_SEED)

# ─── SUMO scenario rebuild (regenerate from site1.json / phase_plan / events)
SUMO_SITE_DIR    := $(EXPERIMENTS)/sumo/site1
PHASE2_EVENTS    ?= data/events/phase2.ndjson

sumo-build: setup ## Rebuild the SUMO 4-way network from site1.example.json
	$(VENV_PY) $(SUMO_SITE_DIR)/build_site1_network.py \
		--site-meta $(SITE_METADATA) \
		--out-dir $(SUMO_SITE_DIR)/synth

sumo-tllogic: setup ## Regenerate tl.add.xml from phase_plan.yml
	$(VENV_PY) $(SUMO_SITE_DIR)/build_site1_tllogic.py \
		--phase-plan $(PHASE_PLAN_YAML) \
		--net  $(SUMO_SITE_DIR)/synth/net.net.xml \
		--out  $(SUMO_SITE_DIR)/synth/tl.add.xml

sumo-routes: setup ## Regenerate routes.rou.xml from Phase 2 stop_line_crossing events
	$(VENV_PY) $(SUMO_SITE_DIR)/build_site1_routes.py \
		--events     $(PHASE2_EVENTS) \
		--site-meta  $(SITE_METADATA) \
		--out        $(SUMO_SITE_DIR)/synth/routes.rou.xml

sumo-detectors: setup ## Regenerate detectors.add.xml (22 induction loops)
	$(VENV_PY) $(SUMO_SITE_DIR)/build_site1_detectors.py \
		--profiles $(PROFILES_YAML) \
		--out      $(SUMO_SITE_DIR)/synth/detectors.add.xml

sumo-scenario: sumo-build sumo-tllogic sumo-routes sumo-detectors ## Rebuild every SUMO input in one shot

# ─── Google Maps Routes API — live + typical traffic ────────────────────────
GMAPS_ROUTES_YAML ?= phase1-sandbox/configs/gmaps_routes.yml
GMAPS_DATE        ?= $(shell .venv/bin/python -c "from datetime import date, timedelta; t=date.today(); d=((6-t.weekday())%7) or 7; print((t+timedelta(days=d)).isoformat())")
GMAPS_INTERVAL_MIN ?= 30
GMAPS_POLL_S      ?= 300
GMAPS_TYPICAL_OUT ?= data/research/gmaps/typical_$(GMAPS_DATE).ndjson
GMAPS_LIVE_OUT    ?= data/events/gmaps_traffic.ndjson

gmaps-once: ## Single live call for every corridor (smoke test the API key)
	$(VENV_PY) -m traffic_intel_sandbox.ingest.gmaps poll \
		--config $(GMAPS_ROUTES_YAML) --out $(GMAPS_LIVE_OUT) --once

gmaps-typical: ## One-shot fetch of Google's typical traffic for next Sunday (192 calls ≈ $2)
	$(VENV_PY) -m traffic_intel_sandbox.ingest.gmaps typical \
		--config $(GMAPS_ROUTES_YAML) \
		--date $(GMAPS_DATE) \
		--interval-min $(GMAPS_INTERVAL_MIN) \
		--out $(GMAPS_TYPICAL_OUT)

gmaps-up: ## Start the live polling daemon in the background
	@if [ -f /tmp/traffic-intel-gmaps.pid ] && kill -0 $$(cat /tmp/traffic-intel-gmaps.pid) 2>/dev/null; then \
	    echo "already running (pid $$(cat /tmp/traffic-intel-gmaps.pid))"; exit 0; fi
	@mkdir -p $(dir $(GMAPS_LIVE_OUT))
	@nohup $(VENV_PY) -m traffic_intel_sandbox.ingest.gmaps poll \
		--config $(GMAPS_ROUTES_YAML) --out $(GMAPS_LIVE_OUT) \
		--interval-s $(GMAPS_POLL_S) \
		> /tmp/traffic-intel-gmaps.log 2>&1 & echo $$! > /tmp/traffic-intel-gmaps.pid
	@sleep 1 && echo "gmaps-poll pid $$(cat /tmp/traffic-intel-gmaps.pid)  log=/tmp/traffic-intel-gmaps.log"

gmaps-down: ## Stop the live polling daemon
	@if [ -f /tmp/traffic-intel-gmaps.pid ] && kill -0 $$(cat /tmp/traffic-intel-gmaps.pid) 2>/dev/null; then \
	    kill $$(cat /tmp/traffic-intel-gmaps.pid) && echo "stopped"; else echo "not running"; fi
	@rm -f /tmp/traffic-intel-gmaps.pid

# ─── Forecasting — anchor video + Google profile → day prediction ───────────
FORECAST_VIDEO       ?= data/raw/youtube/anchor.mp4
FORECAST_VIDEO_URL   ?= https://www.youtube.com/watch?v=52ao3WsInBo
FORECAST_T0          ?= 13:00
FORECAST_SITE        ?= data/forecast/forecast_site.json
FORECAST_EVENTS      ?= data/forecast/anchor_events.ndjson
FORECAST_TYPICAL     ?= data/research/gmaps/typical_$(GMAPS_DATE).parquet
FORECAST_MAX_FRAMES  ?= 900
FORECAST_DAY_JSON    ?= data/forecast/forecast_day.json

forecast-download: ## Fetch the anchor YouTube video
	@mkdir -p $(dir $(FORECAST_VIDEO))
	$(VENV)/bin/yt-dlp -f "bv*[height<=1080][ext=mp4]+ba/best[height<=1080]" \
	    -o "$(dir $(FORECAST_VIDEO))anchor.%(ext)s" \
	    --merge-output-format mp4 "$(FORECAST_VIDEO_URL)"

forecast-calibrate: ## Extract keyframe + default stop-lines for the anchor video
	$(VENV_PY) -m traffic_intel_sandbox.forecast.calibrate \
	    --video $(FORECAST_VIDEO) --out-dir data/forecast

forecast-observe: ## Run YOLO26 on the anchor video; write anchor_events.ndjson
	$(VENV_PY) -m traffic_intel_phase2.detect_track \
	    --source $(FORECAST_VIDEO) \
	    --model yolo26n.pt --tracker botsort.yaml \
	    --metadata $(FORECAST_SITE) \
	    --events-out $(FORECAST_EVENTS) \
	    --video-out data/forecast/anchor_annotated.mp4 \
	    --max-frames $(FORECAST_MAX_FRAMES)

forecast-predict: ## Full-day prediction; pass T=HH:MM for single-slot print
	$(VENV_PY) -m traffic_intel_sandbox.forecast.predict \
	    --anchor-events $(FORECAST_EVENTS) \
	    --typical       $(FORECAST_TYPICAL) \
	    --t0            $(FORECAST_T0) \
	    --out           $(FORECAST_DAY_JSON) \
	    $(if $(T),--at $(T))

forecast-all: forecast-download forecast-calibrate forecast-observe forecast-predict ## End-to-end anchor → forecast

research-compose: setup ## Stage 04: composite labeled synthetic video
	$(VENV_PY) $(EXPERIMENTS)/04_compose_synthetic_video.py \
		--plate $(RESEARCH_DIR)/plates/wadisaqra_plate.jpg \
		--crops-dir $(RESEARCH_DIR)/crops \
		--trajectories $(RESEARCH_DIR)/sumo/trajectories_$(RESEARCH_DATE).parquet \
		--site-meta $(SITE_METADATA) \
		--out-video $(RESEARCH_DIR)/composed/video.mp4 \
		--out-labels $(RESEARCH_DIR)/composed/labels.json \
		--seconds $(RESEARCH_SECONDS) \
		--seed $(RESEARCH_SEED)

research-events: setup ## Stage 05: seeded §6.6 event clips (stalled, spillback, …)
	$(VENV_PY) $(EXPERIMENTS)/05_generate_event_clips.py \
		--out-root $(RESEARCH_DIR)/events \
		--plate $(RESEARCH_DIR)/plates/wadisaqra_plate.jpg \
		--crops-dir $(RESEARCH_DIR)/crops \
		--site-meta $(SITE_METADATA) \
		--per-class $(RESEARCH_PER_CLASS) \
		--seconds $(RESEARCH_EVENT_SECONDS) \
		--seed $(RESEARCH_SEED)

research-all: research-frames research-segment research-sumo research-compose research-events ## Run the full sim-to-real pipeline end-to-end

# ─── Cleaning ────────────────────────────────────────────────────────────────
clean-synth: ## Remove synthetic artifacts (keeps raw videos)
	rm -rf $(COUNTS_DIR)/*.parquet $(SIGNALS_DIR)/*.ndjson

clean: clean-synth ## Remove all derived artifacts (keeps raw videos)
	rm -rf $(NORMALIZED_VIDEO_DIR)/* $(HISTORICAL_DIR)/*

clean-all: clean ## Also remove raw videos (destructive)
	rm -rf $(RAW_VIDEO_DIR)/*.mp4

.PHONY: help setup docker-pull \
        fetch-videos normalize-videos historical-pack veo3-ingest \
        stream-up stream-check stream-down \
        synth-counts synth-signals synth-all \
        validate-metadata \
        annotation-up annotation-seed annotation-down \
        sandbox-up sandbox-verify sandbox-down sandbox-package viewer \
        phase2-detect phase2-live phase2-live-bg phase2-live-down phase2-classify \
        research-frames research-segment research-sumo research-compose research-events research-all \
        clean-synth clean clean-all
