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
RAW_VIDEO_DIR        ?= $(DATA_DIR)/raw/youtube
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

# ─── RTSP stream ─────────────────────────────────────────────────────────────
stream-up: ## Start MediaMTX + publish first normalized clip in a loop
	docker compose up -d mediamtx postgres
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

sandbox-down: stream-down annotation-down ## Stop all sandbox services

sandbox-package: ## Tar data + docs into dist/sandbox-v1.tar.zst (needs zstd)
	mkdir -p dist
	tar --zstd -cf dist/sandbox-v1.tar.zst \
		data/detector_counts data/signal_logs data/metadata \
		phase1-sandbox/data_dictionary.md phase1-sandbox/methodology.md

# ─── Cleaning ────────────────────────────────────────────────────────────────
clean-synth: ## Remove synthetic artifacts (keeps raw videos)
	rm -rf $(COUNTS_DIR)/*.parquet $(SIGNALS_DIR)/*.ndjson

clean: clean-synth ## Remove all derived artifacts (keeps raw videos)
	rm -rf $(NORMALIZED_VIDEO_DIR)/* $(HISTORICAL_DIR)/*

clean-all: clean ## Also remove raw videos (destructive)
	rm -rf $(RAW_VIDEO_DIR)/*.mp4

.PHONY: help setup docker-pull \
        fetch-videos normalize-videos historical-pack \
        stream-up stream-check stream-down \
        synth-counts synth-signals synth-all \
        validate-metadata \
        annotation-up annotation-seed annotation-down \
        sandbox-up sandbox-verify sandbox-down sandbox-package \
        clean-synth clean clean-all
