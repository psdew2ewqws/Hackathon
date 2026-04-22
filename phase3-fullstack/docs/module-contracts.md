# Phase 3 — Module Contracts

Python-side public API for every module in the stack. Signatures pulled from
source; changes to these surfaces are breaking for callers. File paths are
repo-relative.

## Acquisition

Path: `phase3-fullstack/scripts/run_rtsp.sh`,
`phase3-fullstack/bin/mediamtx`, `phase3-fullstack/configs/mediamtx.yml`.

Acquisition is shell+binary, not Python. MediaMTX listens on `:8554`;
`run_rtsp.sh` discovers the archived mp4 via `configs/wadi_saqra.json
→ video.file` and re-publishes it as `rtsp://127.0.0.1:8554/wadi_saqra`.
The tracker opens that URL with OpenCV `cv2.VideoCapture(url, cv2.CAP_FFMPEG)`;
reconnect logic lives inside the tracker (see below), not in a separate
acquisition layer.

## Tracker

Path: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/tracker.py`.

```python
@dataclass
class TrackerConfig:
    rtsp_url: str
    model_path: Path
    zones_path: Path
    ingest_fps: float = 10.0
    bin_seconds: int = 15
    counts_ndjson: Path | None = None
    tracker_yaml: str = "bytetrack.yaml"
    imgsz: int = 960

class TrackerService:
    def __init__(self, cfg: TrackerConfig) -> None: ...
    def on_bin(self, cb: Callable[[dict], None]) -> None: ...
    def on_frame(self, cb: Callable[[float, list[int], list[tuple[float,float]],
                                     dict[int, str|None], dict[str, str]], None]) -> None: ...
    def start(self) -> None: ...   # spawns daemon thread
    def stop(self) -> None: ...    # joins with 5 s timeout
    state: TrackerState            # counts, fps, frame_ts, last_jpeg, running, last_error
```

Bin record (`on_bin` payload):
`{bin_start, bin_end, seconds, in_zone: {a: int}, crossings_in_bin: {a: int},
crossings_total: {a: int}, fps}`.

## Counters

Path: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/counters.py`.

```python
@dataclass
class Zone:
    approach: str; label: str
    polygon: np.ndarray                                     # (N, 2) int32
    stop_line: tuple[tuple[int, int], tuple[int, int]] | None
    direction_of_travel: str                                # "up"|"down"|"left"|"right"

def load_zones(path: Path) -> list[Zone]: ...
def point_in_polygon(point: tuple[float, float], polygon: np.ndarray) -> bool: ...
def segments_cross(p1, p2, q1, q2) -> bool: ...
def crossed_in_direction(prev_xy, curr_xy, stop_line, direction: str) -> bool: ...

class ApproachCounter:
    def __init__(self, zones: Iterable[Zone]) -> None: ...
    def update(self, track_ids: list[int], centroids: list[tuple[float,float]]) -> None: ...
    def approach_map(self) -> dict[int, str | None]: ...
    def direction_map(self) -> dict[str, str]: ...
    def snapshot(self) -> dict[str, dict[str, int]]: ...   # {a: {in_zone, crossings_total}}
    def reset_crossings(self) -> None: ...
```

## Event Engine

Path: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/events.py`.

```python
class EventEngine:
    def __init__(self, ndjson_path: Path | None = None, buffer_size: int = 500) -> None: ...
    def on_event(self, cb: Callable[[dict], None]) -> None: ...
    def on_bin(self, bin_record: dict, fused: dict[str, dict] | None = None) -> None: ...
    def on_track_frame(self, ts: float,
                       track_ids: list[int],
                       centroids: list[tuple[float, float]],
                       approach_for_track: dict[int, str | None],
                       approach_directions: dict[str, str],
                       signal_phase_name: str | None,
                       signal_state: str | None) -> None: ...
    def classify_recent_incidents(self, window_s: float = 30.0) -> list[dict]: ...
    def recent(self, limit: int = 50, event_type: str | None = None) -> list[dict]: ...
    def close(self) -> None: ...
```

Event record shape: `{ts, event_id, event_type, approach, severity,
confidence, payload, snapshot_hint}` — see `events.py` module docstring.

## Signal Simulator

Path: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/signal_sim.py`.

```python
@dataclass(frozen=True)
class CurrentPlan:
    NS_green: float = 35.0
    EW_green: float = 35.0
    yellow:   float = 3.0
    all_red:  float = 2.0
    @property
    def cycle_seconds(self) -> float: ...          # sum + 2*(yellow+all_red)

class SignalSimulator:
    def __init__(self, intersection_id: str, plan: CurrentPlan,
                 ndjson_path: Path | None = None) -> None: ...
    def on_event(self, cb: Callable[[dict], None]) -> None: ...
    def start(self) -> None: ...
    def stop(self)  -> None: ...
    def snapshot(self) -> dict: ...                # {running, plan, current}
    def recent(self, limit: int = 50) -> list[dict]: ...

def generate_day(plan: CurrentPlan, intersection_id: str,
                 day_start: datetime, day_end: datetime) -> list[dict]: ...
```

## Fusion + Webster

Path: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/fusion.py`.

```python
@dataclass(frozen=True)
class GmapsRow:
    corridor: str; local_hour: float
    congestion_ratio: float; congestion_label: str
    duration_s: float; static_duration_s: float
    speed_kmh: float; static_speed_kmh: float

def load_gmaps(path: Path, local_hour: float) -> dict[str, GmapsRow]: ...
def load_gmaps_all(path: Path) -> dict[str, dict[float, GmapsRow]]: ...
def classify_pressure(pressure: float) -> str: ...      # 'free' .. 'jam'
def gmaps_intensity(row: GmapsRow) -> float: ...

def fuse(approach_counts: dict[str, dict[str, int]],
         bin_seconds: int,
         gmaps_rows: dict[str, GmapsRow]) -> dict[str, dict]: ...

def forecast_per_approach(fused_now: dict[str, dict],
                          gmaps_now: dict[str, GmapsRow],
                          gmaps_target: dict[str, GmapsRow]) -> dict[str, dict]: ...

def build_heatmap(fused_now: dict[str, dict],
                  all_rows: dict[str, dict[float, GmapsRow]],
                  current_hour: float) -> dict: ...

def webster_two_phase(fused: dict[str, dict],
                      current_plan: dict | None = None,
                      saturation: float = 25.0,
                      yellow_per_phase: float = 3.0,
                      all_red_per_phase: float = 2.0,
                      min_green: float = 10.0,
                      max_green: float = 90.0) -> dict: ...
# Backwards-compat alias:
webster_recommendation = webster_two_phase
```

## Forecast Bridge (LightGBM)

Path: `phase3-fullstack/src/forecast_ml/` (CLI entrypoints
`forecast-ml-train` and `forecast-ml-predict` via `pyproject.toml`).

```python
# forecast_ml/features.py
BIN_MIN       = 15                    # 15-minute bins
LAGS          = [1, 2, 4, 96, 672]    # 15min, 30min, 1h, 1d, 7d
HORIZONS_BINS = [0, 1, 2, 4]          # +0, +15, +30, +60 min

def build_features(counts_dir: Path, signal_dir: Path) -> FeatureBuild: ...
def feature_columns() -> list[str]: ...
def target_columns()  -> list[str]: ...    # ['y_now','y_15min','y_30min','y_60min']

# forecast_ml/predict.py
def predict_at(target_ts: pd.Timestamp,
               counts_dir: Path = Path("data/detector_counts"),
               lgb_bundle: Path = Path("models/forecast_lgb.json")) -> dict: ...
```

Artefacts: `models/forecast_lgb.json` (4 boosters + feature_cols),
`models/forecast_metrics.json` (train/val MAE + metadata).

## Storage

Path: `phase3-fullstack/src/traffic_intel_phase3/storage/`.

```python
# db.py
class Db:
    def __init__(self, path: Path | str = DEFAULT_DB) -> None: ...
    def execute(self, sql: str, params=()) -> sqlite3.Cursor: ...
    def executemany(self, sql: str, rows) -> sqlite3.Cursor: ...
    def executescript(self, script: str) -> None: ...
    def query_all(self, sql: str, params=()) -> list[dict]: ...
    def query_one(self, sql: str, params=()) -> dict | None: ...
    def transaction(self): ...                          # context manager
    def close(self) -> None: ...

def get_db(path: Path | str | None = None) -> Db: ...   # process-wide singleton
def init_schema(db: Db) -> None: ...
def close_shared() -> None: ...

# sinks.py
class StorageSink:
    def __init__(self, db: Db | None = None,
                 flush_s: float = 1.0, batch_size: int = 200) -> None: ...
    def start(self) -> None: ...
    def stop(self, drain: bool = True) -> None: ...
    def push(self, kind: str, row: dict) -> None: ...
    # kinds: detector_count | signal_event | incident | forecast
    #        recommendation | ingest_error | system_metric | audit
```

## Auth

Path: `phase3-fullstack/src/traffic_intel_phase3/auth/`.

```python
# jwt_service.py
@dataclass(frozen=True)
class TokenPayload: username: str; role: str; exp: int

class JwtService:
    def __init__(self, secret: str, ttl_minutes: int = 30,
                 issuer: str = "traffic-intel") -> None: ...
    def issue(self, username: str, role: str) -> tuple[str, TokenPayload]: ...
    def verify(self, token: str) -> TokenPayload: ...   # raises jwt.InvalidTokenError

def make_service() -> JwtService: ...                   # reads TRAFFIC_INTEL_JWT_{SECRET,TTL_MIN}

# users.py
@dataclass(frozen=True)
class UserRecord: id: int; username: str; role: Role  # Literal[viewer|operator|admin]

class UsersRepository:
    def __init__(self, db: Db | None = None) -> None: ...
    def create(self, username: str, password: str, role: Role) -> UserRecord: ...
    def find  (self, username: str) -> tuple[UserRecord, str] | None: ...
    def verify(self, username: str, password: str) -> UserRecord | None: ...
    def list  (self) -> list[UserRecord]: ...
    def delete(self, username: str) -> int: ...

def ensure_default_users(repo: UsersRepository | None = None) -> list[UserRecord]: ...

# deps.py
@dataclass(frozen=True)
class AuthContext: username: str; role: str

def get_auth_context(request: Request,
                     credentials = Depends(_bearer)) -> AuthContext: ...
def require_role(min_role: str) -> Callable[..., AuthContext]: ...
```

## FastAPI endpoints (REST + WS)

Path: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/server.py`.

```
POST /api/auth/login           body: {username, password} → {token, username, role, expires_at}
GET  /api/auth/me              auth: bearer               → {username, role}
GET  /api/audit/log            auth: admin                → {events: [...]}
GET  /api/health                                          → {tracker, signal_sim, storage, sink_queue}
GET  /api/site                                            → site config JSON
GET  /api/counts                                          → latest tracker snapshot
GET  /api/gmaps?hour=                                     → per-corridor gmaps rows
GET  /api/fusion                                          → fuse() output
GET  /api/recommendation                                  → fuse + webster_two_phase
GET  /api/forecast?hour=                                  → gmaps-anchored forecast + Webster
GET  /api/forecast/horizon?start=&hours=&step=            → rolling N-hour series
GET  /api/heatmap                                         → 24h × 4 approach pressure grid
GET  /api/signal/current                                  → signal_sim.snapshot()
GET  /api/signal/log?limit=                               → recent phase events
GET  /api/events?limit=&event_type=                       → event engine recent
POST /api/events/_demo         auth: admin                → emits one of each detector
GET  /mjpeg                                               → annotated MJPEG multipart stream
WS   /ws/counts                                           → tracker bin broadcasts
WS   /ws/signal                                           → signal phase broadcasts
WS   /ws/events                                           → event engine broadcasts
```
