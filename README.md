# Traffic-Intel — First-Site AI Traffic Intelligence

**9XAI Hackathon build.** End-to-end traffic monitoring, incident detection, flow forecasting, and operator-facing dashboard for one representative intersection, designed to scale to multiple sites.

## Phases

| Phase | Status | Dir | Purpose |
|---|---|---|---|
| **1. Sandbox** | ▶ building | [`phase1-sandbox/`](phase1-sandbox/) | Realistic simulated feeds + synthetic datasets that mimic live traffic operations |
| 2. Feasibility | next | [`phase2-feasibility/`](phase2-feasibility/) | YOLO26 detection+tracking, forecasting, dashboard quick builds |
| 3. Full-Stack | later | [`phase3-fullstack/`](phase3-fullstack/) | Integrated working system across all mandatory modules |

Planning doc: `/home/admin1/.claude/plans/i-have-a-project-cached-peacock.md`
Hackathon handbook: `/home/admin1/Downloads/9XAI Hackathon Handbook  AI-Based Traffic Monitoring and Traffic Flow Forecasting.docx`

## Quickstart

```bash
# 1. One-time: create venv + install deps + pull docker images
make setup
make docker-pull

# 2. Populate YouTube sources in phase1-sandbox/configs/sources.yml, then:
make fetch-videos
make normalize-videos
make historical-pack

# 3. Bring the sandbox online
make sandbox-up            # MediaMTX + Postgres + RTSP publisher
make stream-check          # Verify rtsp://localhost:8554/site1 at 1920x1080 / 5-15 fps

# 4. Generate synthetic datasets
make synth-all             # detector counts (parquet) + signal logs (ndjson)

# 5. Validate intersection metadata
make validate-metadata

# 6. End-to-end verification
make sandbox-verify        # runs pytest suite
```

All commands: `make help`

## Repo Layout (top level)

```
traffic-intel/
├── Makefile                   # single entry-point
├── docker-compose.yml         # mediamtx + postgres (+ cvat profile)
├── pyproject.toml             # traffic_intel_sandbox package
├── data/                      # gitignored artifacts
├── phase1-sandbox/
│   ├── src/traffic_intel_sandbox/   # Python package (ingest/, rtsp_sim/, synth/, metadata/, annotation/)
│   ├── scripts/publish_loop.sh      # ffmpeg → RTSP loop
│   ├── configs/                     # sources.yml, profiles.yml, phase_plan.yml
│   ├── tests/                       # pytest suite (sandbox-verify)
│   ├── data_dictionary.md
│   └── methodology.md
├── phase2-feasibility/        # scaffolded
└── phase3-fullstack/          # scaffolded
```

## Principles

- **Read-only toward operational infrastructure** — no control commands, ever (handbook §11).
- **Modular** — every component is an independent Python CLI or container with a typed input/output contract.
- **Reproducible** — `make sandbox-verify` must stay green on a fresh clone.
- **Open-source only** — MIT / Apache / AGPL-3.0 components; no paid lock-in (handbook §11).

## Licenses

Application code: MIT. See `phase1-sandbox/methodology.md` for the full open-source component list and their individual licenses.
