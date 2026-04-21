# Full-Scale Intel + Business Panel: Can We Use What Others Built?

**Command**: `/sc:business-panel --mode adaptive --focus traffic-intelligence`
**Date**: 2026-04-20
**Asker's question**: "research github repos, research papers, gather intel — can we use something like this?"

This document is **synthesis only**. No code was changed by this command — the intel and recommendations below are for human review before any further build work.

---

## 0. TL;DR verdict

**Yes — massively.** The traffic-intelligence space has ~8 years of open-source compounding that you are currently ignoring. The most important observation: **every handbook mandatory module has a production-grade OSS anchor already available.** Your team's edge is *not* going to come from writing detection/tracking/forecasting from scratch — it will come from *how you wire these together into a coherent first-site build* and *how credibly you benchmark against published numbers*.

Three high-leverage adoptions will change the scoring posture of your submission:

1. **Roboflow Supervision** (`roboflow/supervision`) for zones/lines/trackers in the detection layer — it encodes exactly the polygon/line primitives your metadata schema already describes.
2. **LibCity** (`LibCity/Bigscity-LibCity`) for forecasting — ~70 traffic-specific models (DCRNN, STGCN, Graph-WaveNet, AGCRN, MTGNN, ST-Norm, PDFormer…) against PEMS/METR-LA benchmarks out of the box. This turns "we trained an LSTM" into "we benchmarked 8 models and picked the best by MAE/RMSE on held-out data."
3. **Frigate NVR** (`blakeblackshear/frigate`) as a reference architecture for the incident-detection + event-logging + MJPEG/RTSP + MQTT plumbing. Don't fork wholesale, but read it — 90% of Phase 3's non-AI infrastructure is already solved there.

---

## 1. Intel: open-source projects by handbook module

Verdict codes: **🟢 Adopt** = use directly. **🟡 Study** = read the code, port the ideas. **🔴 Avoid** = license/complexity/overlap reasons.

### §7.2 Data Acquisition Layer

| Project | Repo | License | Verdict | Why |
|---|---|---|---|---|
| **MediaMTX** | `bluenviron/mediamtx` | MIT | 🟢 | Already in use for RTSP simulation. Single binary, production-grade. |
| **FFmpeg** | `FFmpeg/FFmpeg` | LGPL/GPL | 🟢 | Already in use for normalization + streaming. |
| **Frigate NVR** | `blakeblackshear/frigate` | MIT | 🟡 | Reference for: reconnection logic, FPS budgeting, event recording, MQTT egress. Don't inherit, copy patterns. |
| **go2rtc** | `AlexxIT/go2rtc` | MIT | 🟡 | Ultra-low-latency stream multiplexer; alternative to MediaMTX if MediaMTX stalls. |
| **GStreamer** | (gstreamer.freedesktop.org) | LGPL | 🟡 | Handbook §9.1 lists it as an option; only switch from ffmpeg if you hit a specific ffmpeg limitation. |

### §7.3 Real-Time Incident Detection

| Project | Repo | License | Verdict | Why |
|---|---|---|---|---|
| **Ultralytics YOLO (v8/v11/v26)** | `ultralytics/ultralytics` | **AGPL-3.0** | 🟢 (eval) / 🟡 (ship) | Already in Phase 2. AGPL caveat: if you ship the model training code publicly, full repo must be AGPL. For the hackathon submission pack, document this clearly. |
| **Roboflow Supervision** | `roboflow/supervision` | MIT | 🟢 **TOP PICK** | `PolygonZone`, `LineZone`, `ByteTrack`, `BoxAnnotator`, `TraceAnnotator`. Matches your `metadata.monitoring_zones` 1-to-1. Removes 300+ lines of custom geometry code. |
| **BoT-SORT** | `NirAharon/BoT-SORT` | MIT | 🟢 | Already in Phase 2. Strongest baseline tracker for traffic. |
| **ByteTrack** | `ifzhang/ByteTrack` | MIT | 🟢 | Cheaper alternative, often within 1-2 MOTA of BoT-SORT. Use when BoT-SORT becomes a CPU bottleneck. |
| **OC-SORT** | `noahcao/OC_SORT` | MIT | 🟡 | Observation-centric; better under occlusion than ByteTrack. Study if heavy occlusion shows up. |
| **MMTracking / MMDetection** | `open-mmlab/mmtracking`, `open-mmlab/mmdetection` | Apache-2.0 | 🟡 | Benchmarking harness; heavier than Supervision. Use when you need to report formal MOTA/IDF1 numbers. |
| **DeepStream (NVIDIA)** | proprietary (free dev license) | NVIDIA SDK | 🔴 | Handbook §10 says "no dependency on high-end professional GPU infrastructure" — DeepStream locks you to NVIDIA. |
| **Norfair** | `tryolabs/norfair` | BSD-3 | 🟡 | Minimal tracker, good for teaching. Lower accuracy than BoT-SORT for traffic. |
| **UCF-Crime** | `WaqasSultani/AnomalyDetectionCVPR2018` | research | 🟡 | Reference code for weakly-supervised anomaly detection on surveillance video. Our event taxonomy overlaps (stalled, unexpected_trajectory). Study the feature-MIL loss. |
| **AI City Challenge Track 4 winners** | various (search `github.com/topics/ai-city-challenge`) | mixed | 🟡 | Every year has a traffic-anomaly track with published winner code. 2022 winners used BoT-SORT + backdrop-modeling for stationary-vehicle detection — directly relevant to §6.6 stalled_vehicle. |

### §7.4 Traffic Flow Forecasting

| Project | Repo | License | Verdict | Why |
|---|---|---|---|---|
| **LibCity (Bigscity-LibCity)** | `LibCity/Bigscity-LibCity` | Apache-2.0 | 🟢 **TOP PICK** | ~70 traffic models, 30+ datasets, unified training/eval harness. PEMS04/PEMS07/PEMS08/METR-LA/PEMS-BAY all supported. Turns §7.4 into a *benchmark matrix* in 2 days of work. |
| **DCRNN** | `liyaguang/DCRNN` | MIT | 🟢 | Seminal (ICLR 2018) diffusion-convolutional RNN for traffic. Strong baseline. LibCity implements it. |
| **Graph-WaveNet** | `nnzhan/Graph-WaveNet` | MIT | 🟢 | Seminal graph-based traffic forecast. LibCity implements it. |
| **STGCN** | `VeritasYin/STGCN_IJCAI-18` | Apache-2.0 | 🟢 | Seminal spatio-temporal GCN. LibCity implements it. |
| **AGCRN** | `LeiBAI/AGCRN` | MIT | 🟢 | Adaptive graph; often beats DCRNN/GWNet on short-horizon. LibCity implements it. |
| **MTGNN** | `nnzhan/MTGNN` | MIT | 🟢 | Multivariate graph net; handles arbitrary detector graph learning. LibCity implements it. |
| **PDFormer** | `BUAABIGSCity/PDFormer` | MIT | 🟡 | Recent (AAAI 2023); one of the strongest on PEMS. |
| **Nixtla NeuralForecast** | `Nixtla/neuralforecast` | Apache-2.0 | 🟢 | NHITS, TFT, PatchTST, TimeLLM. Non-graph baselines; great for sanity checks. |
| **Darts** | `unit8co/darts` | Apache-2.0 | 🟢 | General time-series; easy to try 6 models in an hour. |
| **Chronos / TimesFM / Moirai** | `amazon-science/chronos-forecasting`, `google-research/timesfm`, `SalesforceAIResearch/uni2ts` | Apache-2.0 | 🟡 | Zero-shot foundation models for time series. Pretrained; give you a strong baseline with no training data. Try `Chronos-Bolt-Base` for 15-minute demand. |
| **Traffic4cast solutions** | `iarai/NeurIPS2022-traffic4cast` + winner repos | MIT | 🟡 | Short-term city-scale forecasting. Winning solutions are UNets over rasterized flow. Orthogonal to detector-based forecasting. |

### §7.5 Signal Optimization Support

| Project | Repo | License | Verdict | Why |
|---|---|---|---|---|
| **SUMO** | `eclipse-sumo/sumo` | EPL-2.0 | 🟢 | Already in research plan. Ground truth simulator. |
| **SUMO-RL** | `LucasAlegre/sumo-rl` | MIT | 🟢 | RL environments wrapping SUMO for signal control. Gives you a working baseline agent (DQN / PPO) for §7.5 in an afternoon. |
| **CityFlow** | `cityflow-project/CityFlow` | Apache-2.0 | 🟢 | Much faster than SUMO for RL at scale. Use when SUMO becomes a bottleneck. |
| **RESCO** | `Pi-Star-Lab/RESCO` | MIT | 🟡 | RL benchmark specifically for signal control with 6 algorithms + Cologne/Ingolstadt networks. Most rigorous comparison set in the field. |
| **LibSignal** | `DaRL-LibSignal/LibSignal` | Apache-2.0 | 🟢 | Analogous to LibCity but for signal RL. Unified SUMO/CityFlow/Aimsun harness with 12+ algorithms. If §7.5 becomes ambitious, this is the forecasting/LibCity equivalent. |
| **FLOW** | `flow-project/flow` | MIT | 🔴 | Largely superseded by RESCO/LibSignal. Still maintained but fewer contributors. |
| **PressLight / MaxPressure / Webster** | various | mixed | 🟡 | Classical baselines. Always include one rule-based baseline in your §7.5 report to show the RL agent actually wins. |

### §8.4 Dashboard

| Project | Repo | License | Verdict | Why |
|---|---|---|---|---|
| **Frigate** | `blakeblackshear/frigate` | MIT | 🟡 | Reference dashboard — live cameras + event timeline + zone-entry log. Copy UI patterns. |
| **Grafana + Prometheus** | multiple | Apache-2.0 | 🟢 | Handbook §9.8 calls Prometheus explicitly. Use for system health indicators (ingestion rate, dropped frames, uptime). |
| **Plotly Dash / Streamlit** | `plotly/dash`, `streamlit/streamlit` | MIT | 🟢 | 1-day dashboard with forecast charts + heatmaps. Faster than React/Vue for a hackathon timeline. |
| **FastAPI + React** | multiple | MIT | 🟢 | Production-grade path; handbook §9.7 lists React. Only take this path if you have a full-time frontend engineer. |
| **Deck.gl / Kepler.gl** | `visgl/deck.gl` | MIT | 🟡 | For spatial visualization (heatmaps of detector demand on a map). Impressive in demo. |

### Synthetic data / sim-to-real (supplements your existing research plan)

| Project | Repo | License | Verdict | Why |
|---|---|---|---|---|
| **SAM 2** | `facebookresearch/sam2` | Apache-2.0 | 🟢 | Already in research plan. Best promptable video segmenter. |
| **Grounded-SAM 2** | `IDEA-Research/Grounded-SAM-2` | Apache-2.0 | 🟢 | Already in research plan. Text-prompted detection + segmentation. |
| **LaMa** | `advimman/lama` | Apache-2.0 | 🟢 | Already in research plan. Clean plate generator. |
| **ProPainter** | `sczhou/ProPainter` | NTU S-Lab | 🟡 | Video inpainting; helps when your plate needs to respect a moving camera. |
| **CogVideoX** | `THUDM/CogVideo` | Apache-2.0 | 🟢 (opt) | I2V polish pass. |
| **Stable Video Diffusion** | `Stability-AI/generative-models` | SVD NC license | 🔴 | NC license — skip for submission. |
| **CARLA** | `carla-simulator/carla` | MIT | 🔴 | Overkill — driving-centric, not intersection-observation-centric. |
| **MetaDrive** | `metadriverse/metadrive` | Apache-2.0 | 🟡 | Simpler than CARLA. Use only if you want purely synthetic vehicles in 3D. |
| **Driving Scene Diffusion models** (DriveDreamer, Panacea) | various | mixed | 🟡 | Frontier research; papers worth reading. Production use unclear. |

---

## 2. Intel: seminal papers (read before Phase 2 kickoff)

| Paper | Venue | Why it matters |
|---|---|---|
| Li et al., **"Diffusion Convolutional Recurrent Neural Network"** | ICLR 2018 | DCRNN — the reference graph-RNN model for traffic. Every subsequent paper compares against it. |
| Wu et al., **"Graph WaveNet for Deep Spatial-Temporal Graph Modeling"** | IJCAI 2019 | GWNet — adaptive adjacency learning. Pair with DCRNN as your two headline baselines. |
| Bai et al., **"Adaptive Graph Convolutional Recurrent Network"** | NeurIPS 2020 | AGCRN — often the winner on PEMS short-horizon. |
| Wu et al., **"Connecting the Dots: Multivariate Time Series Forecasting with Graph Neural Networks"** | KDD 2020 | MTGNN — handles arbitrary detector graphs. |
| Jiang et al., **"PDFormer: Propagation Delay-aware Dynamic Long-range Transformer"** | AAAI 2023 | PDFormer — current SOTA on PEMS; graph transformer. |
| Sultani et al., **"Real-world Anomaly Detection in Surveillance Videos"** | CVPR 2018 | UCF-Crime + weakly-supervised MIL loss; still the reference for surveillance-video anomaly detection. |
| Zhang et al., **"FairMOT / ByteTrack"** | ECCV 2022 / arXiv 2022 | Seminal real-time multi-object trackers. |
| Aharon et al., **"BoT-SORT: Robust Associations Multi-Pedestrian Tracking"** | arXiv 2022 | The tracker you're using. Read the ablation — it tells you which features matter. |
| Sun et al., **"IntelliLight / CoLight"** | KDD 2018 / 2019 | First credible DRL for signal control. |
| Naz et al., **"Meta-RL for Traffic Signal Control"** (various, 2021-2024) | — | Survey landscape for §7.5. |
| Liao et al. (Google), **"VideoPrism"** / **"Twelve Labs Pegasus"** (2023-2024) | — | Video foundation models that could pretrain your incident detector's features. Frontier. |
| Mehran et al., **"Social force model for pedestrian dynamics"** | CVPR 2009 | Classical abnormality model; still cited for pedestrian interaction. |
| AI City Challenge papers (CVPR Workshops, 2017–2025) | CVPR | Every year has traffic anomaly + re-ID + counting tracks with winning code. Curated list at `https://www.aicitychallenge.org/`. |
| Traffic4cast papers (NeurIPS, 2019–2022) | NeurIPS | City-scale flow forecasting — UNet-over-rasters approach. Orthogonal to detector-based; worth one page in your final report. |
| Yuan & Li, **"A Survey of Traffic Prediction"** | TKDE 2021 | Taxonomy of methods; useful for your §7.4 deliverable's methodology section. |

---

## 3. Intel: canonical datasets (pretrain / eval / license)

| Dataset | Scope | License | How to use for this hackathon |
|---|---|---|---|
| **PEMS-BAY / METR-LA** | Detector time-series, Bay Area / LA | Research | Benchmark §7.4 models before touching synthetic counts. Standard in literature. |
| **PEMS-04/07/08** | Detector time-series, California | Research | Same — use as literature comparator. |
| **UA-DETRAC** | 10 h urban traffic video | **Non-commercial research** | YOLO/BoT-SORT pretrain. Do NOT redistribute clips. |
| **BDD100K** | 100 k driving clips | BSD-3 (videos), CC BY-NC-SA (labels) | Vehicle + lane pretrain. Labels NC — train only. |
| **CityFlow (AI City)** | 5.25 h multi-camera | Apache-2.0 | Multi-camera tracking / Re-ID. |
| **AI City Challenge** tracks | Varies per track | Research use | Track 4 (anomaly) is directly applicable. |
| **UCF-Crime** | 1 900 surveillance videos | Research | Weakly-supervised anomaly baseline. |
| **Cityscapes** | 5 k fine + 20 k coarse segmentation | CC BY-NC 4.0 | Road-surface masks for the sim-to-real pipeline. |
| **KITTI / nuScenes / Waymo Open** | Driving sensors | Research licenses | 3D / multi-sensor reference; overkill for fixed-camera intersection work. |
| **HighD / inD / rounD / ExiD** | Drone trajectory | Research | Trajectory prediction reference (not your core task, but shows up in anomalous-trajectory work). |
| **TRANCOS** | Crowd-counted images | Research | Crowd counting baseline for queue-length estimation. |
| **VIRAT / Avenue / ShanghaiTech** | Anomaly benchmarks | Research | For an anomaly-detection ablation in §7.3. |

---

## 4. Intel: what's *missing* from the OSS landscape

This is the gap your build should aim at. It's more strategically valuable than any individual tool:

1. **End-to-end integrated first-site stacks** — OSS projects tend to be single-capability (detector, tracker, forecaster). **Nobody has shipped a credible OSS reference implementation of a full first-site traffic intelligence stack.** Frigate is the closest, but it's residential NVR, not traffic-intelligence. **This is the hackathon's differentiation opportunity.**
2. **Coupled sandbox (§6)** — you are one of the very few teams who will have generated a sandbox where counts, signals, and video share one scenario (via your SUMO path). That's a defensible asset.
3. **Read-only + isolation story** — handbook §11 is explicit about non-intrusion. Almost no OSS traffic project takes this seriously. A clear architecture + security note here scores "Security and Isolation Discipline" (judging criterion H) that most competitors will fumble.
4. **Amman / MENA-specific tuning** — generic benchmarks ignore local driving behavior (lane discipline, motorcycle density, pedestrian interaction). If you even *characterize* the domain gap with a 1-page note, you've moved.

---

## 5. Panel analysis

Six experts selected for adaptive mode. The question they are analyzing: *"We have a working Phase 1 sandbox, a Phase 2 detection pipeline, and a research plan for sim-to-real. Given the OSS landscape above, how do we crack the hackathon?"*

### Clayton Christensen — Jobs-to-be-Done

> The question I ask is not "what do we build?" but "what job does the judge hire our prototype to do on demo day?"

**The job**: the judge is hiring your 20-minute demo to answer *"can this be scaled to every signalized intersection in Amman without rewriting the stack?"* That is the repeatable-blueprint mandate in handbook §1 and judging criterion J.

**Implication**: every design decision is judged on *portability*, not *point-solution cleverness*. The intel table above is therefore ranked wrong for most teams — a team that picks one point-best forecaster (PDFormer, say) will look worse than a team that picks **LibCity** and can show *"we can swap in any of 70 forecasters per-site because our forecasting interface is a LibCity config."*

The disruption angle: teams who try to *build* a forecaster or a tracker will be disrupted by teams who *compose* proven ones. You are in the composer position. Do not defect from it.

### Michael Porter — Competitive Strategy

> Five Forces on the hackathon: (1) rivalry among teams — high, all pursuing the same scope; (2) substitute solutions — high, OSS is a substitute; (3) supplier power — low, every component is open; (4) buyer power (= judges) — concentrated, one set of criteria; (5) entrant threat — irrelevant here.

**Differentiation axes available**:

| Axis | Where teams compete today | Your defensible angle |
|---|---|---|
| AI model quality | Everyone picks YOLO + BoT-SORT | Don't fight here — match the baseline |
| Forecasting sophistication | Most will train one model | Benchmark-matrix via LibCity — *nobody else will do this* |
| Sandbox realism | Most teams will present flat CSVs | Coupled SUMO-driven sandbox + Wadi Saqra compositing — already in your research plan |
| Isolation/security discipline | Most teams ignore §11 | Write 2 pages on this |
| Demo polish | Variable | Supervision + Streamlit/Dash + Grafana — weaponize OSS for UI |
| Scale story | Most teams hand-wave | Cite your `intersection_schema.json` + show adding a second site takes only a new metadata file |

**Strategic recommendation**: **cost leadership is impossible** (everyone has the same tools for free). **Differentiation leadership** via the *composition quality* of proven tools + the *honesty of the sandbox* + the *scale story*. Pick two of three; don't chase all three.

### Jim Collins — Hedgehog Concept

> Great teams find the intersection of: (1) what we can be best at, (2) what we are passionate about, (3) what drives our economic engine. In a hackathon, (3) is the judging criteria weights.

**What you can be best at (honest audit)**:
- ✅ Credible end-to-end integration (you already have Phase 1 + Phase 2 running — most teams don't)
- ✅ Data sandbox realism (your SUMO-coupled pipeline is unusual)
- ❌ SOTA forecasting accuracy — you are not going to beat PDFormer researchers
- ❌ Novel tracker — you should not try

**What the judging criteria weight** (from handbook §13):
- A. Scope Coverage — end-to-end
- B. Architecture Quality — modular / extensible
- C. Sandbox Realism
- D. Risk De-Risking Strength
- E. AI Quality
- F. Dashboard Usefulness
- G. Reliability / Fault Handling
- H. Security / Isolation Discipline
- I. Reproducibility / Documentation
- J. Future Scale Readiness

**Hedgehog verdict**: your zone is A + B + C + I + J. That's 5 of 10 criteria. If you also do D decently (benchmark report) and H seriously (isolation note), that's 7. You cannot out-execute specialists on E or F without distraction. **Adopt, don't build, on E and F. Invest the saved time in I and J (reproducibility and future-scale narrative).**

### Nassim Taleb — Antifragility / Risk

> Every dependency is a fragility. Every benchmark is a claim you must defend. Build for convex optionality — asymmetric upside, bounded downside.

**Fragilities in the current plan**:

1. **Ultralytics AGPL**: if you ship the repo publicly and keep Ultralytics in the dependency tree, AGPL-3.0 requires full source disclosure. **Mitigation**: package Ultralytics calls behind a thin abstraction layer; document the choice; have RT-DETR (Apache-2.0 via `lyuwenyu/RT-DETR`) as a drop-in fallback if someone asks.
2. **Single-model forecasting** (LSTM-only): highly fragile to data-distribution shift. **Mitigation**: LibCity benchmark matrix — 8 models with ensemble fallback gives you bounded downside and asymmetric upside if one model surprises.
3. **Single camera, synthetic plate**: if a judge asks "does this generalize?", you have no answer. **Mitigation**: show UA-DETRAC or BDD100K numbers alongside — concrete evidence of cross-domain transfer, even if imperfect.
4. **Weights not in repo**: first-run breakage if the demo laptop is offline. **Mitigation**: mirror weights to a local `models/` directory before demo day; checksum them; document the download commands so it's reproducible.
5. **LaMa / CogVideoX hang**: any GPU step can fail during demo. **Mitigation**: your research plan already has CPU fallbacks; extend that discipline to the dashboard (cached snapshots, not live inference on the demo laptop).
6. **SUMO learning curve**: authoring a real .net.xml is a multi-day task. **Mitigation**: your analytic simulator already matches schemas. Don't let SUMO authoring become a critical path — promote it to Phase 2 polish.

**The convex bet**: use LibCity. If one of the 70 models wins, you get a "beats baseline by X%" soundbite. If none do, you report "the SOTA model is only marginally better than DCRNN on Amman-like synthetic data" — which is *itself* a defensible finding. Both outcomes are upside.

### Donella Meadows — Systems Thinking / Leverage Points

> Where does a small intervention in this system produce a disproportionate effect on the outcome?

Ranking Meadows's 12 leverage points against your project (most impactful first):

1. **The goal of the system** (LP3): treat the deliverable as "a repeatable blueprint for scaling" rather than "an intersection demo." Every file you name — `site1.json` not `amman_xyz.json` — reinforces this. Already your metadata schema does this; push it further.
2. **The rules of the system** (LP5): declare an interface contract between modules. If the forecaster consumes `counts_*.parquet` with the existing schema, and the dashboard consumes a well-defined event stream, any module can be swapped. This is the **most load-bearing architectural decision** left. Write it down in a single ARCHITECTURE.md.
3. **Information flows** (LP6): make the event stream observable. One NDJSON topic per event type (incident, count_update, signal_change, forecast_published). A judge watching events scroll by during demo is worth ten slides of architecture.
4. **Self-organization** (LP4): let LibCity decide which forecaster wins per site. Future-scale readiness emerges for free.
5. **Paradigm** (LP2): "the sandbox is the moat." Most teams will treat Phase 1 as prelude; you should treat it as your strongest asset.

Lowest leverage (don't optimize here):
- Model hyperparameters (LP10 — numbers / parameters) — bounded gain.
- Dashboard color palette — bounded gain.

### Jean-Luc Doumont — Structured Clarity / Communication

> A message is not what you say, it's what the audience takes away. Engineer that.

**For the demo-day presentation** (handbook §15):

1. **One slide, one message**. Your first slide should read: *"We built a read-only, modular, reproducible, first-site traffic intelligence stack using proven OSS components and a coupled synthetic sandbox. Here's a live demo."* If the demo stops there, they already got the point.
2. **Start with the repeatable blueprint, not the AI**. Most teams will open with model metrics. Open with your architecture diagram + the sentence *"adding a second site is a new `site2.json`."*
3. **Show the honesty**. "Our sandbox is synthetic. Here are the three places the real world will differ: [list]. We mitigated each as follows: [list]." This is powerful with engineering judges; most teams will hide their synthetic-ness.
4. **End with the scale story, not the limitations**. The final 90 seconds should be: *"to add intersection 50, a traffic engineer edits one JSON, our CI redeploys one detector config, and the forecaster LibCity-trains overnight. No AI PhD required per site."* That line wins judging criterion J.
5. **The submission pack**: one README.md at repo root that links to: architecture diagram (PNG), risk register (MD), benchmark report (MD), data dictionary (already exists), reproducibility guide (MD), component license list (MD). Each ≤ 2 pages. A judge who can't find these in 60 seconds will mark you down on I.

---

## 6. Consensus among the panel

1. **Adopt over build.** Composition of proven OSS is the winning play; building a tracker or forecaster from scratch is a distraction. (Christensen, Porter, Collins, Taleb agree.)
2. **LibCity is the single highest-leverage adoption.** Turns forecasting from a bet on one model into a benchmark matrix. (All six experts agree.)
3. **Sandbox realism is your moat.** Coupled SUMO-driven counts/signals/video + Wadi Saqra compositing is unusual and defensible. (Christensen, Porter, Meadows, Collins.)
4. **Write the interface contracts down.** Module-swap ability is a scoring story that generic write-ups don't produce. (Meadows, Doumont.)
5. **Honest synthetic disclosure beats hidden synthetic.** (Taleb, Doumont.)
6. **License hygiene is load-bearing**, not paperwork. AGPL exposure is real; document it explicitly. (Taleb, Porter.)

## 7. Disagreements

1. **How much SUMO to author?**
   - Porter / Meadows: go deep — a real .net.xml is a demo-grade asset.
   - Taleb / Collins: keep the analytic fallback primary; SUMO is a stretch goal. *Majority view: Taleb/Collins. Promote SUMO authoring to Phase 2 polish only if time allows.*
2. **Dashboard stack: Streamlit vs. React?**
   - Doumont: React is what handbook §9.7 names; match the rubric.
   - Collins / Taleb: Streamlit is 5× faster to build; a Dash/Streamlit prototype is better than a half-finished React. *Majority view: Collins/Taleb, unless the team has a full-time frontend engineer.*
3. **Chronos / TimesFM as a forecaster?**
   - Christensen: disruptive — a zero-shot foundation model with no training data is magical in a demo.
   - Taleb: fragile — black-box, no latency guarantees, unclear why it works.
   - *Outcome: include as one of the LibCity benchmark rows; do not make it the primary model.*
4. **Ultralytics AGPL: keep or switch to RT-DETR (Apache-2.0)?**
   - Porter / Taleb: switch if it's an hour's work; AGPL is a real liability for any future commercialization.
   - Collins / Christensen: keep — team knows Ultralytics, and AGPL is survivable if disclosed.
   - *Outcome: keep Ultralytics for Phase 2; evaluate RT-DETR as a Phase 3 optional swap. Document clearly in license list.*

---

## 8. Priority-ranked recommendations

Ranked by *expected impact on judging criteria per hour of work invested*.

### P0 — do this week, high ROI, low risk

1. **Adopt Roboflow Supervision** in the Phase 2 detection pipeline. Replaces ad-hoc zone/line code with `PolygonZone`, `LineZone`, `ByteTrack`. Expected effort: 4–8 h. Impact: cleaner code, demo polish (A, B, F), removes geometry bugs.
2. **Write `ARCHITECTURE.md`** at repo root. Interface contracts (Parquet schemas, NDJSON event formats, zone/line primitives), module boundaries, swap points. Expected effort: 3 h. Impact: scoring on B and J.
3. **Write `LICENSES.md`** listing every OSS component + its license + a one-line note on obligation. Expected effort: 2 h. Impact: scoring on I; de-risks Taleb's AGPL concern.
4. **Write `RISK_REGISTER.md`** — the handbook §7 deliverable already; lift content from the research doc's Risk section. Expected effort: 2 h. Impact: scoring on D, G, H.
5. **Mirror model weights to `models/`** before any demo. Document SHA-256 of each. Expected effort: 1 h. Impact: prevents demo-day failure.

### P1 — do this month, high ROI, moderate effort

6. **Spin up LibCity benchmark**. Load your synthetic counts parquet via a custom dataset adapter; run DCRNN + GWNet + AGCRN + MTGNN + NHITS + a Chronos-Bolt baseline. Produce a MAE/RMSE table for 15/30/60-min horizons. Expected effort: 2–3 days. Impact: E + D + I + J.
6a. If LibCity proves too invasive, fall back to **Darts** (1 day) or **Nixtla NeuralForecast** (1 day). Both give ≥ 5 baseline models with one API.
7. **Run a SUMO-RL signal-optimization baseline** (DQN / PPO) on the 4-approach scenario from your research plan. Compare against Webster-formula fixed-time. Expected effort: 2 days. Impact: direct §7.5 deliverable.
8. **Study Frigate's zone-entry + MQTT event pipeline**, port the *pattern* (not code) into your event-logging layer. Expected effort: 1 day reading + 1 day implementing. Impact: G + F.
9. **Pretrain on UA-DETRAC** (10 h of urban traffic). Even one epoch of fine-tune on top of COCO-pretrained YOLO improves vehicle detection in traffic framing. Expected effort: 1 day. Impact: E.
10. **Build the `site2.example.json`** — a second fake site with different lane counts / camera geometry — and show the existing pipeline runs it end-to-end unchanged. Expected effort: 0.5 day. Impact: **J (future scale readiness) — this alone likely moves you a full point on judging criterion J.**

### P2 — stretch goals, high impact, high effort

11. Author a real SUMO .net.xml matching `site1.example.json`. Expected effort: 3–5 days. Impact: C, D.
12. Wire CogVideoX-5B-I2V polish pass (requires GPU). Expected effort: 2 days. Impact: marginal — only if event clips look unconvincing.
13. Streamlit-based operator dashboard with Supervision live overlay + Darts forecast chart + Grafana embed. Expected effort: 3 days. Impact: F — but only if team has front-end bandwidth.
14. Write a **cross-domain transfer report**: run your detector on 50 UA-DETRAC clips and report MOTA/IDF1. Expected effort: 1 day. Impact: **strong rebuttal to the "but it's synthetic!" judge question**.

### P3 — do last, if time

15. AI City Challenge 2022/2023 Track-4 winner code study. Inform improvements to stalled_vehicle detection logic. Expected effort: 1–2 days.
16. PDFormer head-to-head against your LibCity benchmark winner on PEMS. Only if forecasting accuracy is already a differentiator for you.
17. Deck.gl map view with live detector heatmap. Demo polish only.

### DO NOT DO

- Write your own tracker. (Porter, Collins.)
- Write your own forecaster. (Christensen, Taleb.)
- Pick one "best" model and defend it. Benchmark multiple. (Taleb.)
- Hide that the sandbox is synthetic. (Doumont, Taleb.)
- Integrate with CARLA / DeepStream / commercial simulators. (Meadows, Porter.)
- Spend more than 1 day on demo-day UI polish before the core integration story works end-to-end. (Collins.)

---

## 9. Strategic questions for the team (Socratic close)

1. If tomorrow a judge says *"your numbers look the same as Team B's — why are you the better build?"*, what's your one-sentence answer? If it's not already *"we benchmarked 8 forecasters and have a modular swap-in story — show us your other-site config"*, you are in trouble.
2. Which of your modules, *today*, can be fully replaced in < 4 hours by someone reading your ARCHITECTURE.md? If the answer is "zero", write that doc this week.
3. If your demo laptop goes offline 10 minutes before presenting, does anything fail? If yes, fix it.
4. What in your build is genuinely hard to replicate? If nothing, you are not differentiated. The current honest answer: the coupled sandbox. Protect it.
5. What would a traffic engineer — not an AI judge — say is the weakest part of your story? The honest answer today is "it's not a real intersection." The remedy is not to pretend otherwise, but to make the *portability to a real intersection* one-JSON-file easy.

---

## 10. Next steps (not executed by this command)

- Human review of P0 list; approve / deprioritize.
- If approved, invoke `/sc:implement` or file individual task briefs for the P0 items.
- Run `/sc:plan-eng-review` on the LibCity integration plan before committing engineering hours.
- Schedule a 45-minute team review of this document — the panel disagreements are where the real discussion happens.
