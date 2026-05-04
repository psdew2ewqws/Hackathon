import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  apiUrl,
  getCounts,
  getFusion,
  getHeatmap,
  getForecast,
  getRecommendation,
  getSite,
  wsUrl,
} from '../api/client';
import {
  APPROACH_COLOR,
  APPROACHES,
  type Approach,
  type CongestionLabel,
  type CountsResponse,
  type FusionResponse,
  type HeatmapResponse,
  type ForecastResponse,
  type RecommendationResponse,
  type SiteConfig,
} from '../api/types';
import { ApproachCard } from '../components/ApproachCard';
import { ApproachZoneEditor } from '../components/ApproachZoneEditor';
import { DetectorBackendToggle } from '../components/DetectorBackendToggle';
import { LaneOverlay } from '../components/LaneOverlay';
import { LaneQuickEditor } from '../components/LaneQuickEditor';
import { Pill } from '../components/Pill';
import { LineChart } from '../components/charts';

// Order the right rail S, N, E, W as specified.
const CARD_ORDER = APPROACHES;

// ── Live Signal + log + events types (inline — not in types.ts since only
// the Live page consumes them) ──
interface SignalEvent {
  timestamp: string;
  intersection_id: string;
  cycle_number: number;
  phase_number: number;
  phase_name: 'NS' | 'EW' | 'E' | 'W';
  signal_state: string;
  approaches_affected: Approach[];
  duration_seconds: number;
}
interface SignalCurrentResp {
  running: boolean;
  intersection_id: string;
  plan: {
    NS_green: number;
    EW_green: number;
    yellow: number;
    all_red: number;
    cycle_seconds: number;
    mode?: 'two_phase' | 'three_phase';
    E_green?: number;
    W_green?: number;
  };
  current: SignalEvent | null;
}
interface SignalLogResp {
  events: SignalEvent[];
}

interface LiveEvent {
  ts: string;
  event_id: string;
  event_type: string;
  approach?: Approach;
  severity: 'info' | 'warning' | 'critical';
  confidence?: number;
  payload?: Record<string, unknown>;
}
interface LiveEventsResp {
  events: LiveEvent[];
}

interface HorizonTickResp {
  hour: number;
  per_approach: Record<
    Approach,
    {
      pressure: number | null;
      label: CongestionLabel | null;
      gmaps_ratio: number | null;
      gmaps_label: CongestionLabel | null;
      gmaps_speed_kmh: number | null;
      scale_vs_now: number | null;
    }
  >;
  recommended: {
    cycle_seconds: number;
    NS_green: number;
    EW_green: number;
    delay_reduction_pct: number;
  };
}
interface HorizonResp {
  start_hour: number;
  hours: number;
  step: number;
  baseline_hour: number;
  ticks: HorizonTickResp[];
}

interface Demand15MinResp {
  window_min: number;
  approaches: Approach[];
  history: Record<Approach, { bucket_start: string; count: number }[]>;
  forecast: {
    available: boolean;
    per_detector?: Record<string, {
      approach: Approach;
      y_now: number;
      y_15min: number;
      y_30min: number;
      y_60min: number;
    }>;
  };
  generated_at: string;
}

interface RecommendationForecastResp {
  look_ahead_hours: number;
  target_hour: number;
  baseline_hour: number;
  predicted: Record<Approach, { pressure?: number; label?: string }>;
  recommendation: RecommendationResponse['recommendation'];
  anticipated_peak: {
    hour: number;
    approach: Approach;
    label: string;
    pressure: number | null;
  } | null;
  advisory_only: boolean;
}

// ── Small helpers ──
function fmtTime(hr: number): string {
  const h = Math.floor(hr);
  const m = Math.round((hr - h) * 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}
function fmtScale(v: number | null | undefined): string {
  if (v == null) return '-';
  const pct = Math.round((v - 1) * 100);
  return `${pct >= 0 ? '+' : ''}${pct}%`;
}
function stateColor(state: string | undefined | null): string {
  if (!state) return '#2a2f38';
  if (state.includes('GREEN')) return '#22c55e';
  if (state.includes('YELLOW')) return '#eab308';
  if (state.includes('RED')) return '#ef4444';
  return '#2a2f38';
}
const LABEL_BG: Record<string, string> = {
  free: '#14532d',
  light: '#1e40af',
  moderate: '#78350f',
  heavy: '#7c2d12',
  jam: '#7f1d1d',
};
const LABEL_RANK: Record<string, number> = {
  free: 0,
  light: 1,
  moderate: 2,
  heavy: 3,
  jam: 4,
};
const EVENT_COLOR: Record<string, string> = {
  congestion_class_change: '#86efac',
  queue_spillback: '#fdba74',
  abnormal_stopping: '#fde68a',
  stalled_vehicle: '#bfdbfe',
  wrong_way: '#fecaca',
  incident: '#fecaca',
};
function sevColor(s: string): string {
  if (s === 'critical') return '#fecaca';
  if (s === 'warning') return '#fde68a';
  return '#86efac';
}

// ── Reusable styles ──
const cardStyle: React.CSSProperties = {
  background: '#121820',
  border: '1px solid #1e2630',
  borderRadius: 10,
  padding: 12,
};
const cardTitle: React.CSSProperties = {
  fontSize: 12,
  margin: '0 0 10px',
  letterSpacing: '.06em',
  textTransform: 'uppercase',
  opacity: 0.7,
};
const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 13,
};
const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 8px',
  borderBottom: '1px solid #1e2630',
  fontWeight: 500,
  opacity: 0.7,
};
const tdStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 8px',
  borderBottom: '1px solid #1e2630',
};

export function LivePage() {
  const [site, setSite] = useState<SiteConfig | null>(null);
  const [counts, setCounts] = useState<CountsResponse | null>(null);
  const [fusion, setFusion] = useState<FusionResponse | null>(null);
  const [rec, setRec] = useState<RecommendationResponse | null>(null);
  const [recForecast, setRecForecast] = useState<RecommendationForecastResp | null>(null);
  const [wsStatus, setWsStatus] = useState<'connecting' | 'open' | 'closed'>(
    'connecting',
  );
  const wsRef = useRef<WebSocket | null>(null);

  // One-time site fetch
  useEffect(() => {
    const ac = new AbortController();
    getSite(ac.signal).then(setSite).catch(() => {});
    return () => ac.abort();
  }, []);

  // On page (re)load, restart the RTSP loop so the video begins at frame 0
  // and the signal-cycle anchor (NS GREEN @ 0:00) aligns with what the
  // operator is watching.
  useEffect(() => {
    fetch(apiUrl('/api/video/restart'), { method: 'POST' }).catch(() => {});
  }, []);

  // Poll counts + fusion + recommendation each second
  useEffect(() => {
    let alive = true;
    let t: number;
    const tick = async () => {
      try {
        const [c, f, r] = await Promise.all([
          getCounts(),
          getFusion(),
          getRecommendation(),
        ]);
        if (!alive) return;
        setCounts(c);
        setFusion(f);
        setRec(r);
      } catch {
        /* next tick retries */
      }
      if (alive) t = window.setTimeout(tick, 1000);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  // Poll the 1-hour look-ahead recommendation + anticipated peak once per minute.
  useEffect(() => {
    let alive = true;
    const fetchLookahead = async () => {
      try {
        const r = await fetch(apiUrl('/api/recommendation/forecast'));
        if (!r.ok) return;
        const j = (await r.json()) as RecommendationForecastResp;
        if (alive) setRecForecast(j);
      } catch {
        /* ignore */
      }
    };
    fetchLookahead();
    const id = window.setInterval(fetchLookahead, 60_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  // WS: reconnect on close. We only use it as a bin-tick cue.
  useEffect(() => {
    let closed = false;
    let retry: number;
    const connect = () => {
      const ws = new WebSocket(wsUrl('/ws/counts'));
      wsRef.current = ws;
      setWsStatus('connecting');
      ws.onopen = () => setWsStatus('open');
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg?.type === 'bin' && msg.record) {
            getCounts().then(setCounts).catch(() => {});
          }
        } catch {
          /* non-JSON — ignore */
        }
      };
      ws.onclose = () => {
        setWsStatus('closed');
        if (!closed) retry = window.setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  const fused = fusion?.fused ?? ({} as FusionResponse['fused']);
  const capturedLocal = site?.video?.captured_at_local;
  const lat = site?.lat;
  const lng = site?.lng;

  return (
    <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <AdvisoryBanner />
      {recForecast?.anticipated_peak && (
        <AnticipatedCongestionBanner peak={recForecast.anticipated_peak} />
      )}
      <SystemHealthStrip />
      <TopBar
        counts={counts}
        wsStatus={wsStatus}
        capturedLocal={capturedLocal}
        lat={lat}
        lng={lng}
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.5fr) minmax(280px, 1fr)',
          gap: 14,
        }}
      >
        <section style={cardStyle}>
          <h2 style={cardTitle}>Annotated RTSP feed</h2>
          <DetectorBackendToggle />
          <LaneQuickEditor />
          <ApproachZoneToggleAndEditor />
          <div style={{ position: 'relative', width: '100%', maxWidth: 960 }}>
            <img
              src={apiUrl('/mjpeg')}
              alt="live"
              style={{
                width: '100%',
                aspectRatio: '16 / 9',
                display: 'block',
                background: '#000',
                borderRadius: 8,
                objectFit: 'cover',
              }}
            />
            <LaneOverlay />
          </div>
        </section>

        <section
          style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
        >
          {CARD_ORDER.map((a) => {
            const c = counts?.counts?.[a];
            const bin = counts?.crossings_in_current_bin?.[a] ?? 0;
            return (
              <ApproachCard
                key={a}
                approach={a}
                inZone={c?.in_zone ?? 0}
                crossingsTotal={c?.crossings_total ?? 0}
                crossingsInBin={bin}
                fused={fused[a]}
              />
            );
          })}
        </section>
      </div>

      <SignalPlanPanel rec={rec} recForecast={recForecast} />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)',
          gap: 14,
        }}
      >
        <LiveSignalStatePanel />
        <RecentSignalEventsPanel />
      </div>

      <LiveEventsPanel />

      <ForecastChartsPanel />

      <ForecastVsGmapsPanel />

      <ForecastAccuracyPanel />

      <ForecastHeatmapPanel />

      <RollingForecastPanel />

      <HistoricalSummaryPanel />

      <footer
        style={{
          opacity: 0.6,
          fontSize: 11,
          padding: '8px 0 14px',
          borderTop: '1px solid #1e2630',
          marginTop: 4,
          display: 'flex',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <span>
          Docs:{' '}
          <a
            href="/api/docs/architecture.md"
            style={{ color: '#bfdbfe' }}
            target="_blank"
            rel="noreferrer"
          >
            architecture
          </a>{' '}
          ·{' '}
          <a
            href="/api/docs/security_and_isolation.md"
            style={{ color: '#bfdbfe' }}
            target="_blank"
            rel="noreferrer"
          >
            security &amp; isolation
          </a>
        </span>
        <span style={{ marginLeft: 'auto' }}>
          Traffic Intel · Phase-2 build
        </span>
      </footer>
    </div>
  );
}

// Top-of-page advisory — constraint visibility for §7.5/§7.7.
// ─────────────────────────────────────────────────────────────
// System health strip — ingest rate, drops, reconnects, isolation
// ─────────────────────────────────────────────────────────────
interface IngestMetricsResp {
  sources: Record<string, {
    source: string;
    uptime_s: number;
    last_ok_ts: number | null;
    last_error_ts: number | null;
    last_error: string | null;
    records_total: number;
    records_dropped: number;
    reconnect_count: number;
    ingest_rate_hz: number | null;
  }>;
}

function SystemHealthStrip() {
  const [metrics, setMetrics] = useState<IngestMetricsResp | null>(null);
  const [health, setHealth] = useState<{ tracker?: { running: boolean; fps: number; last_error: string | null }; storage?: { counts: number; signals: number; incidents: number }; sink_queue?: number } | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const [m, h] = await Promise.all([
          fetch(apiUrl('/api/ingest/metrics')).then((r) => r.json()),
          fetch(apiUrl('/api/health')).then((r) => r.json()),
        ]);
        if (alive) {
          setMetrics(m);
          setHealth(h);
        }
      } catch {
        /* ignore */
      }
    };
    poll();
    const id = window.setInterval(poll, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const video = metrics?.sources.video;
  const trackerOk = health?.tracker?.running ?? false;
  const sinkQ = health?.sink_queue ?? 0;

  const chip = (label: string, value: string | number, ok: boolean, detail?: string) => (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        padding: '6px 10px',
        border: '1px solid #1e2630',
        borderRadius: 8,
        background: '#0b0f14',
        minWidth: 100,
      }}
    >
      <span style={{ fontSize: 10, opacity: 0.6, textTransform: 'uppercase', letterSpacing: '.06em' }}>
        {label}
      </span>
      <span
        style={{
          fontSize: 14,
          fontWeight: 700,
          color: ok ? '#86efac' : '#fecaca',
        }}
      >
        {value}
      </span>
      {detail && (
        <span style={{ fontSize: 10, opacity: 0.6 }}>{detail}</span>
      )}
    </div>
  );

  return (
    <div
      style={{
        display: 'flex',
        gap: 10,
        flexWrap: 'wrap',
        padding: '10px 12px',
        background: '#121820',
        border: '1px solid #1e2630',
        borderRadius: 10,
      }}
    >
      {chip('Tracker', trackerOk ? 'alive' : 'idle', trackerOk, health?.tracker ? `${health.tracker.fps.toFixed(1)} fps` : '—')}
      {chip('Ingest video', video ? `${video.ingest_rate_hz?.toFixed(2) ?? '—'} hz` : '—', (video?.ingest_rate_hz ?? 0) > 0, video ? `uptime ${Math.floor(video.uptime_s)}s` : undefined)}
      {chip('Dropped', video?.records_dropped?.toString() ?? '0', (video?.records_dropped ?? 0) === 0)}
      {chip('Reconnects', video?.reconnect_count?.toString() ?? '0', (video?.reconnect_count ?? 0) <= 2)}
      {chip('Sink queue', sinkQ.toString(), sinkQ < 50, 'SQLite batched')}
      {chip('Storage', health?.storage?.counts?.toString() ?? '—', true, health?.storage ? `${health.storage.incidents} incidents` : undefined)}
      <div
        style={{
          marginLeft: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '4px 12px',
          borderRadius: 999,
          background: '#14532d',
          color: '#86efac',
          fontSize: 11,
          fontWeight: 600,
        }}
        title="Read-only to source. No outbound control commands."
      >
        <span style={{ width: 8, height: 8, borderRadius: 999, background: '#86efac' }} />
        ISOLATED · READ-ONLY
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Historical summary mini-card — last-24h totals per approach
// ─────────────────────────────────────────────────────────────
interface DailyCountsRow {
  date: string;
  approach: Approach;
  total: number;
}
interface DailyIncidentsRow {
  date: string;
  event_type: string;
  severity: 'info' | 'warning' | 'critical';
  n: number;
}
interface DailyResp {
  counts_by_day?: DailyCountsRow[];
  incidents_by_day?: DailyIncidentsRow[];
}

function HistoricalSummaryPanel() {
  const [resp, setResp] = useState<DailyResp | null>(null);
  const [lastFetched, setLastFetched] = useState<number | null>(null);
  const [prevGrand, setPrevGrand] = useState<number | null>(null);
  const [delta, setDelta] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const r = await fetch(apiUrl('/api/history/daily?days=1'));
        if (!r.ok) return;
        const j = (await r.json()) as DailyResp;
        if (alive) {
          // compute delta vs previous fetch so the user can see motion.
          const sum = (j.counts_by_day ?? []).reduce((s, x) => s + x.total, 0);
          setDelta(prevGrand != null ? sum - prevGrand : null);
          setPrevGrand(sum);
          setResp(j);
          setLastFetched(Date.now());
        }
      } catch {
        /* ignore */
      }
    };
    poll();
    const id = window.setInterval(poll, 5_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-render once a second so the "updated Xs ago" label ticks.
  const [, forceTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => forceTick((n) => n + 1), 1_000);
    return () => window.clearInterval(id);
  }, []);

  const { totals, incidentsTotal, incidentsByType } = useMemo(() => {
    const tot: Record<Approach, number> = { S: 0, N: 0, E: 0, W: 0 };
    for (const r of resp?.counts_by_day ?? []) {
      if (r.approach in tot) tot[r.approach] += r.total;
    }
    const byType: Record<string, number> = {};
    let incTotal = 0;
    for (const r of resp?.incidents_by_day ?? []) {
      byType[r.event_type] = (byType[r.event_type] ?? 0) + r.n;
      incTotal += r.n;
    }
    return { totals: tot, incidentsTotal: incTotal, incidentsByType: byType };
  }, [resp]);

  const grand = Object.values(totals).reduce((s, v) => s + v, 0);
  const sortedIncidents = Object.entries(incidentsByType)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);

  const ageSec = lastFetched != null ? Math.max(0, Math.floor((Date.now() - lastFetched) / 1000)) : null;

  return (
    <section style={cardStyle}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 10,
          marginBottom: 10,
          flexWrap: 'wrap',
        }}
      >
        <h2 style={{ ...cardTitle, margin: 0 }}>Today so far · live counts</h2>
        <span style={{ fontSize: 11, opacity: 0.6 }}>
          (since local midnight · polling every 5 s)
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 11, opacity: 0.75 }}>
          {ageSec != null ? `updated ${ageSec}s ago` : 'loading…'}
          {delta != null && delta > 0 && (
            <span style={{ marginLeft: 8, color: '#86efac', fontWeight: 600 }}>
              +{delta.toLocaleString()} since last tick
            </span>
          )}
        </span>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(5, 1fr)',
          gap: 10,
        }}
      >
        {(['S', 'N', 'E', 'W'] as const).map((a) => (
          <div
            key={a}
            style={{
              background: '#0b0f14',
              border: '1px solid #1e2630',
              borderRadius: 8,
              padding: 10,
            }}
          >
            <div
              style={{
                fontSize: 28,
                fontWeight: 700,
                color: APPROACH_COLOR[a],
              }}
            >
              {a}
            </div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>{totals[a].toLocaleString()}</div>
            <div style={{ fontSize: 11, opacity: 0.65 }}>crossings</div>
          </div>
        ))}
        <div
          style={{
            background: '#0b0f14',
            border: '1px solid #1e2630',
            borderRadius: 8,
            padding: 10,
          }}
        >
          <div style={{ fontSize: 13, opacity: 0.7, textTransform: 'uppercase', letterSpacing: '.04em' }}>
            Total
          </div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{grand.toLocaleString()}</div>
          <div style={{ fontSize: 11, opacity: 0.65 }}>across all approaches</div>
        </div>
      </div>

      {incidentsTotal > 0 && (
        <div
          style={{
            marginTop: 12,
            padding: 10,
            background: '#0b0f14',
            border: '1px solid #1e2630',
            borderRadius: 8,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: 8,
              marginBottom: 6,
            }}
          >
            <span
              style={{
                fontSize: 11,
                opacity: 0.7,
                textTransform: 'uppercase',
                letterSpacing: '.06em',
              }}
            >
              Incidents last 24h
            </span>
            <strong style={{ fontSize: 16, color: '#fecaca' }}>
              {incidentsTotal.toLocaleString()}
            </strong>
          </div>
          <div
            style={{
              display: 'flex',
              gap: 8,
              flexWrap: 'wrap',
              fontSize: 11,
            }}
          >
            {sortedIncidents.map(([type, n]) => {
              const bg = EVENT_COLOR[type] ?? '#bfdbfe';
              return (
                <span
                  key={type}
                  style={{
                    padding: '3px 8px',
                    borderRadius: 6,
                    background: '#1e2630',
                    color: bg,
                    fontWeight: 600,
                  }}
                >
                  {type}{' '}
                  <span style={{ opacity: 0.8 }}>· {n}</span>
                </span>
              );
            })}
          </div>
        </div>
      )}

      <div style={{ marginTop: 8, fontSize: 11, opacity: 0.6 }}>
        Deeper breakdowns:{' '}
        <a href="#/history" style={{ color: '#bfdbfe' }}>
          History page
        </a>
        {' '}· full event stream:{' '}
        <a href="#/incidents" style={{ color: '#bfdbfe' }}>
          Incidents
        </a>
      </div>
    </section>
  );
}

function AdvisoryBanner() {
  return (
    <div
      style={{
        padding: '8px 14px',
        background: '#0b2e4f',
        color: '#bfdbfe',
        border: '1px solid #1e40af',
        borderRadius: 10,
        fontSize: 12,
      }}
    >
      <strong>Advisory only.</strong> This dashboard surfaces analytics and
      signal-timing recommendations for human operator review. It is
      analytically isolated from operational traffic-signal control and does
      not actuate any infrastructure.
    </div>
  );
}

function AnticipatedCongestionBanner({
  peak,
}: {
  peak: {
    hour: number;
    approach: Approach;
    label: string;
    pressure: number | null;
  };
}) {
  const hh = Math.floor(peak.hour);
  const mm = Math.round((peak.hour - hh) * 60);
  const hhmm = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  const color = peak.label === 'jam' ? '#fecaca' : '#fdba74';
  const bg = peak.label === 'jam' ? '#7f1d1d' : '#7c2d12';
  return (
    <div
      style={{
        padding: '8px 14px',
        background: bg,
        color,
        border: '1px solid #a34816',
        borderRadius: 10,
        fontSize: 12,
      }}
    >
      <strong>Anticipated congestion.</strong> Rolling forecast shows{' '}
      <span style={{ fontWeight: 700 }}>{peak.label.toUpperCase()}</span> on
      approach <span style={{ color: APPROACH_COLOR[peak.approach] }}>{peak.approach}</span> at{' '}
      <strong>{hhmm}</strong>
      {peak.pressure != null && <> (peak pressure {peak.pressure.toFixed(2)})</>}
      . Consider proactive timing review.
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Existing top bar
// ─────────────────────────────────────────────────────────────
interface TopBarProps {
  counts: CountsResponse | null;
  wsStatus: 'connecting' | 'open' | 'closed';
  capturedLocal?: string;
  lat?: number;
  lng?: number;
}

function TopBar({ counts, wsStatus, capturedLocal, lat, lng }: TopBarProps) {
  const running = counts?.running;
  const fps = counts?.fps;
  const bin = counts?.bin_seconds;
  const err = counts?.last_error;
  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        flexWrap: 'wrap',
        alignItems: 'center',
        padding: '10px 14px',
        background: '#121820',
        border: '1px solid #1e2630',
        borderRadius: 10,
        fontSize: 13,
      }}
    >
      <span>
        <Dot color={running ? '#66ff88' : '#ff7a7a'} />
        <strong>{running ? 'live' : 'idle'}</strong>
      </span>
      <span style={{ opacity: 0.8 }}>
        {typeof fps === 'number' ? fps.toFixed(1) : '0.0'} FPS
      </span>
      <span style={{ opacity: 0.8 }}>bin {bin ?? '-'}s</span>
      <span style={{ opacity: 0.6 }}>
        ws: <em>{wsStatus}</em>
      </span>
      {capturedLocal && (
        <span style={{ opacity: 0.7 }}>
          captured&nbsp;
          <code style={{ fontSize: 12 }}>{capturedLocal}</code>
        </span>
      )}
      {lat != null && lng != null && (
        <span style={{ opacity: 0.6, marginLeft: 'auto' }}>
          {lat.toFixed(5)}, {lng.toFixed(5)}
        </span>
      )}
      {err && (
        <span
          style={{
            color: '#fecaca',
            background: '#7f1d1d',
            padding: '2px 8px',
            borderRadius: 6,
            fontSize: 12,
          }}
        >
          {err}
        </span>
      )}
    </div>
  );
}

function Dot({ color }: { color: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: 999,
        background: color,
        marginRight: 6,
      }}
    />
  );
}

// ─────────────────────────────────────────────────────────────
// Panel 1: Signal Plan — current vs Webster. Renders a 2-phase or
// 3-phase table depending on what the backend returns.
// ─────────────────────────────────────────────────────────────
function SignalPlanPanel({
  rec,
  recForecast,
}: {
  rec: RecommendationResponse | null;
  recForecast: RecommendationForecastResp | null;
}) {
  const rec2 = rec?.recommendation;
  const cmp = rec2?.comparison;
  const threePhase = rec2?.mode === 'three_phase';
  const fcRec = recForecast?.recommendation;
  const fcCmp = fcRec?.comparison;
  const fcMode = fcRec?.mode;
  const y = rec2?.flow_ratio_total;
  const phases = rec2?.phases ?? {};
  const yNs = phases.NS?.flow_ratio;
  const yE = phases.E?.flow_ratio;
  const yW = phases.W?.flow_ratio;
  const yEw = phases.EW?.flow_ratio;

  const greenCols = threePhase
    ? [
        { key: 'NS_green', label: 'NS green' },
        { key: 'E_green', label: 'E green' },
        { key: 'W_green', label: 'W green' },
      ]
    : [
        { key: 'NS_green', label: 'NS green' },
        { key: 'EW_green', label: 'EW green' },
      ];

  return (
    <section style={cardStyle}>
      <h2 style={cardTitle}>
        Signal plan · current vs Webster ({threePhase ? '3-phase' : '2-phase'})
      </h2>
      <table style={{ ...tableStyle, maxWidth: 760 }}>
        <thead>
          <tr>
            <th style={thStyle}>Plan</th>
            {greenCols.map((c) => (
              <th key={c.key} style={thStyle}>
                {c.label}
              </th>
            ))}
            <th style={thStyle}>Yellow</th>
            <th style={thStyle}>All-red</th>
            <th style={thStyle}>Cycle</th>
            <th style={thStyle}>Delay (s/veh)</th>
          </tr>
        </thead>
        <tbody>
          {cmp &&
            [
              { name: 'Current (field)', p: cmp.current, color: '#e6edf3' },
              { name: 'Recommended · now', p: cmp.recommended, color: '#66ff88' },
              ...(fcCmp && fcMode === rec2?.mode
                ? [{
                    name: `Recommended · +${recForecast!.look_ahead_hours}h forecast`,
                    p: fcCmp.recommended,
                    color: '#bfdbfe',
                  }]
                : []),
            ].map((row) => (
              <tr key={row.name}>
                <td style={{ ...tdStyle, color: row.color }}>
                  <strong>{row.name}</strong>
                </td>
                {greenCols.map((c) => {
                  const v = (row.p as unknown as Record<string, number | undefined>)[c.key];
                  return (
                    <td key={c.key} style={tdStyle}>
                      {v != null ? `${v.toFixed(1)}s` : '-'}
                    </td>
                  );
                })}
                <td style={tdStyle}>{row.p.yellow.toFixed(1)}s</td>
                <td style={tdStyle}>{row.p.all_red.toFixed(1)}s</td>
                <td style={tdStyle}>{row.p.cycle_seconds.toFixed(1)}s</td>
                <td style={tdStyle}>
                  {row.p.uniform_delay_sec_per_veh.toFixed(2)}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
      <div style={{ marginTop: 10, opacity: 0.9, fontSize: 13 }}>
        Y={y?.toFixed(2) ?? '-'}
        {'  |  '}y_NS={yNs?.toFixed(2) ?? '-'}
        {threePhase ? (
          <>
            {'  '}y_E={yE?.toFixed(2) ?? '-'}
            {'  '}y_W={yW?.toFixed(2) ?? '-'}
          </>
        ) : (
          <>
            {'  '}y_EW={yEw?.toFixed(2) ?? '-'}
          </>
        )}
        {cmp && (
          <>
            {'  |  '}est. delay reduction{' '}
            <strong>
              {cmp.delay_reduction_pct == null
                ? '-'
                : `${cmp.delay_reduction_pct}%`}
            </strong>
          </>
        )}
      </div>
      {rec2?.near_saturation && (
        <div
          style={{
            marginTop: 10,
            padding: '8px 12px',
            background: '#7c2d12',
            color: '#fdba74',
            border: '1px solid #a34816',
            borderRadius: 8,
            fontSize: 12,
          }}
        >
          <strong>Near-saturation</strong> — Y ≥ 0.85. The field plan is at or
          near optimal for current demand; no Webster reshuffle improves delay.
          Advisory only — no signal control is actuated.
        </div>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Panel 2: Live Signal State (polls current + log at 400ms)
// ─────────────────────────────────────────────────────────────
function LiveSignalStatePanel() {
  const [snap, setSnap] = useState<SignalCurrentResp | null>(null);
  const phaseStartRef = useRef<number | null>(null);
  const lastTsRef = useRef<string | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    let t: number;
    const run = async () => {
      try {
        const r = await fetch(apiUrl('/api/signal/current'));
        if (r.ok) {
          const j = (await r.json()) as SignalCurrentResp;
          if (alive) {
            setSnap(j);
            if (j.current && j.current.timestamp !== lastTsRef.current) {
              lastTsRef.current = j.current.timestamp;
              phaseStartRef.current = Date.now();
            }
          }
        }
      } catch {
        /* ignore */
      }
      if (alive) t = window.setTimeout(run, 400);
    };
    run();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  // Local ticker to animate the progress bar smoothly between fetches
  useEffect(() => {
    const id = window.setInterval(() => tick((n) => n + 1), 100);
    return () => window.clearInterval(id);
  }, []);

  const plan = snap?.plan;
  const cur = snap?.current ?? null;
  const threePhase = plan?.mode === 'three_phase';
  const dur = cur?.duration_seconds ?? 1;
  const elapsed = Math.min(
    dur,
    (Date.now() - (phaseStartRef.current ?? Date.now())) / 1000,
  );
  const pct = Math.max(0, Math.min(100, (elapsed / dur) * 100));
  const remain = Math.max(0, dur - elapsed);
  const activePhase = cur?.phase_name;

  const rows: Array<{ label: string; sub: string; phase: string }> = threePhase
    ? [
        { label: 'NS', sub: '(N+S)', phase: 'NS' },
        { label: 'E', sub: '', phase: 'E' },
        { label: 'W', sub: '', phase: 'W' },
      ]
    : [
        { label: 'NS', sub: '(N+S)', phase: 'NS' },
        { label: 'EW', sub: '(E+W)', phase: 'EW' },
      ];

  const planLine = plan
    ? threePhase
      ? `cycle ${plan.cycle_seconds}s · NS green ${plan.NS_green}s · E green ${plan.E_green ?? plan.NS_green}s · W green ${plan.W_green ?? plan.NS_green}s · yellow ${plan.yellow}s · all-red ${plan.all_red}s`
      : `cycle ${plan.cycle_seconds}s · NS green ${plan.NS_green}s · EW green ${plan.EW_green}s · yellow ${plan.yellow}s · all-red ${plan.all_red}s`
    : '—';

  return (
    <section style={cardStyle}>
      <h2 style={cardTitle}>Live signal state (§6.4)</h2>
      <div style={{ fontSize: 13, opacity: 0.8, marginBottom: 10 }}>{planLine}</div>
      {rows.map((r) => {
        const isActive = activePhase === r.phase;
        const state = isActive ? cur!.signal_state : 'RED ON';
        return (
          <SigRow
            key={r.phase}
            label={r.label}
            sub={r.sub}
            state={state}
            pct={isActive ? pct : 0}
            remain={isActive ? remain : null}
          />
        );
      })}
    </section>
  );
}

function SigRow({
  label,
  sub,
  state,
  pct,
  remain,
}: {
  label: string;
  sub: string;
  state: string;
  pct: number;
  remain: number | null;
}) {
  const color = stateColor(state);
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '90px 1fr 1fr',
        gap: 10,
        alignItems: 'center',
        padding: '6px 0',
      }}
    >
      <span
        style={{ fontWeight: 600, fontSize: 14, letterSpacing: '.04em' }}
      >
        {label}{' '}
        <span style={{ opacity: 0.5, fontWeight: 400, fontSize: 11 }}>
          {sub}
        </span>
      </span>
      <span style={{ display: 'flex', alignItems: 'center' }}>
        <span
          style={{
            width: 20,
            height: 20,
            borderRadius: '50%',
            display: 'inline-block',
            marginRight: 6,
            background: color,
            boxShadow:
              color === '#2a2f38'
                ? 'inset 0 0 0 1px #3a414d'
                : `0 0 12px ${color}`,
          }}
        />
        <span>{state}</span>
      </span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            flex: 1,
            height: 8,
            background: '#1e2630',
            borderRadius: 4,
            overflow: 'hidden',
          }}
        >
          <span
            style={{
              display: 'block',
              height: '100%',
              width: `${pct}%`,
              background: '#22c55e',
              transition: 'width .2s linear',
            }}
          />
        </span>
        <span style={{ fontSize: 11, opacity: 0.7, minWidth: 90 }}>
          {remain != null ? `${remain.toFixed(1)}s remaining` : ''}
        </span>
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Panel 3: Recent Signal Events
// ─────────────────────────────────────────────────────────────
function RecentSignalEventsPanel() {
  const [log, setLog] = useState<SignalEvent[]>([]);
  useEffect(() => {
    let alive = true;
    let t: number;
    const run = async () => {
      try {
        const r = await fetch(apiUrl('/api/signal/log?limit=40'));
        if (r.ok) {
          const j = (await r.json()) as SignalLogResp;
          if (alive) setLog(j.events ?? []);
        }
      } catch {
        /* ignore */
      }
      if (alive) t = window.setTimeout(run, 400);
    };
    run();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  return (
    <section style={cardStyle}>
      <h2 style={cardTitle}>Recent signal events</h2>
      <div
        style={{
          maxHeight: 180,
          overflowY: 'auto',
          font: '11px ui-monospace, Menlo, monospace',
        }}
      >
        {log
          .slice()
          .reverse()
          .map((ev, i) => {
            const color = stateColor(ev.signal_state);
            const time = ev.timestamp.split('T')[1]?.replace('+03:00', '') ?? '';
            return (
              <div
                key={`${ev.timestamp}-${i}`}
                style={{
                  padding: '2px 0',
                  borderBottom: '1px solid #1e2630',
                }}
              >
                <span style={{ opacity: 0.6 }}>{time}{'  '}</span>
                <span style={{ fontWeight: 600 }}>{ev.phase_name}{' '}</span>
                <span style={{ color }}>{ev.signal_state}</span>
              </div>
            );
          })}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Panel 4: Live events (§6.6)
// ─────────────────────────────────────────────────────────────
function LiveEventsPanel() {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const refresh = useCallback(async () => {
    try {
      const r = await fetch(apiUrl('/api/events?limit=50'));
      if (r.ok) {
        const j = (await r.json()) as LiveEventsResp;
        setEvents(j.events ?? []);
      }
    } catch {
      /* ignore */
    }
  }, []);
  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 1500);
    return () => window.clearInterval(id);
  }, [refresh]);

  const emitDemo = async () => {
    try {
      await fetch(apiUrl('/api/events/_demo'), { method: 'POST' });
      refresh();
    } catch {
      /* ignore */
    }
  };

  return (
    <section style={cardStyle}>
      <h2 style={cardTitle}>Live events (§6.6)</h2>
      <div
        style={{
          display: 'flex',
          gap: 10,
          marginBottom: 8,
          fontSize: 11,
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        {(
          [
            ['congestion_class_change', '#14532d', '#86efac'],
            ['queue_spillback', '#7c2d12', '#fdba74'],
            ['abnormal_stopping', '#78350f', '#fde68a'],
            ['stalled_vehicle', '#1e40af', '#bfdbfe'],
            ['wrong_way', '#7f1d1d', '#fecaca'],
            ['incident', '#7f1d1d', '#fecaca'],
          ] as const
        ).map(([name, bg, fg]) => (
          <span
            key={name}
            style={{
              background: bg,
              color: fg,
              padding: '2px 8px',
              borderRadius: 999,
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            {name}
          </span>
        ))}
        <span style={{ opacity: 0.6 }}>
          · severity:{' '}
          <strong style={{ color: '#fde68a' }}>warning</strong>/
          <strong style={{ color: '#fecaca' }}>critical</strong>
        </span>
        <button
          onClick={emitDemo}
          style={{
            marginLeft: 'auto',
            background: '#1f2937',
            color: '#e6edf3',
            border: '1px solid #2d3748',
            borderRadius: 6,
            padding: '4px 10px',
            cursor: 'pointer',
            fontSize: 11,
          }}
        >
          Emit demo events
        </button>
      </div>
      <div
        style={{
          maxHeight: 260,
          overflowY: 'auto',
          font: '11px ui-monospace, Menlo, monospace',
        }}
      >
        {events.length === 0 ? (
          <div style={{ opacity: 0.55, padding: '6px 0' }}>
            no events yet (tracker is watching)
          </div>
        ) : (
          events
            .slice()
            .reverse()
            .map((ev) => {
              const c = EVENT_COLOR[ev.event_type] ?? '#e6edf3';
              const t = ev.ts.split('T')[1]?.replace('+03:00', '') ?? '';
              const payload = ev.payload ?? {};
              const bits: string[] = [];
              for (const k of [
                'from',
                'to',
                'queue_count',
                'duration_s',
                'track_id',
                'stationary_seconds',
                'dot_vs_expected',
                'expected_direction',
                'cause',
              ]) {
                const v = (payload as Record<string, unknown>)[k];
                if (v !== undefined && v !== null) bits.push(`${k}=${v}`);
              }
              return (
                <div
                  key={ev.event_id}
                  style={{
                    padding: '2px 0',
                    borderBottom: '1px solid #1e2630',
                  }}
                >
                  <span style={{ opacity: 0.6 }}>{t}{'  '}</span>
                  <span
                    style={{
                      color: sevColor(ev.severity),
                      fontWeight: 600,
                    }}
                  >
                    {ev.severity}
                    {'  '}
                  </span>
                  <span style={{ color: c, fontWeight: 600 }}>
                    {ev.event_type}
                  </span>
                  {ev.approach && (
                    <span
                      style={{
                        color: APPROACH_COLOR[ev.approach],
                        fontWeight: 700,
                        marginLeft: 6,
                      }}
                    >
                      {ev.approach}
                    </span>
                  )}
                  <span style={{ opacity: 0.75, marginLeft: 8 }}>
                    {bits.join('  ')}
                  </span>
                </div>
              );
            })
        )}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Panel 5: Forecast heatmap (24h × 4 approaches) + predicted state
// ─────────────────────────────────────────────────────────────
function ForecastHeatmapPanel() {
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null);
  const [selectedHour, setSelectedHour] = useState<number>(10);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    getHeatmap()
      .then((d) => {
        if (!alive) return;
        setHeatmap(d);
        setSelectedHour(d.current_hour);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Debounce forecast fetch when the slider moves
  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      getForecast(selectedHour)
        .then(setForecast)
        .catch(() => {});
    }, 150);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [selectedHour]);

  if (!heatmap) {
    return (
      <section style={cardStyle}>
        <h2 style={cardTitle}>
          Forecast heatmap (24h · half-hour) — drag slider to pick time
        </h2>
        <div style={{ opacity: 0.6 }}>loading…</div>
      </section>
    );
  }

  const nCols = heatmap.hours.length;
  const gridCols = `40px repeat(${nCols}, 1fr)`;
  const currentHour = heatmap.current_hour;

  return (
    <section style={cardStyle}>
      <h2 style={cardTitle}>
        Forecast heatmap (24h · half-hour) — drag slider to pick time
      </h2>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginBottom: 10,
        }}
      >
        <input
          type="range"
          min={0}
          max={23.5}
          step={0.5}
          value={selectedHour}
          onChange={(e) => setSelectedHour(parseFloat(e.target.value))}
          style={{ flex: 1 }}
        />
        <div style={{ fontSize: 14, minWidth: 180 }}>
          selected <strong>{fmtTime(selectedHour)}</strong>{' · '}
          current <strong>{fmtTime(currentHour)}</strong>
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: gridCols,
            gap: 2,
            minWidth: 900,
          }}
        >
          {(['S', 'N', 'E', 'W'] as const).map((a) => (
            <>
              <div
                key={`lbl-${a}`}
                style={{
                  fontWeight: 700,
                  fontSize: 14,
                  color: APPROACH_COLOR[a],
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'flex-end',
                  paddingRight: 6,
                }}
              >
                {a}
              </div>
              {heatmap.cells[a].map((c) => {
                const bg = c.label
                  ? LABEL_BG[c.label] ?? '#1e2630'
                  : '#1e2630';
                const isSel = c.hour === selectedHour;
                const isCur = c.hour === currentHour;
                const outline = isSel
                  ? '2px solid #e6edf3'
                  : isCur
                    ? '2px dashed #f5a53c'
                    : 'none';
                const title = `${fmtTime(c.hour)} | ${c.label ?? '-'} | p=${c.pressure ?? '-'} | gmaps r=${c.gmaps_ratio ?? '-'} | ${c.gmaps_speed_kmh ?? '-'} km/h`;
                return (
                  <div
                    key={`${a}-${c.hour}`}
                    title={title}
                    onClick={() => setSelectedHour(c.hour)}
                    style={{
                      height: 22,
                      borderRadius: 2,
                      background: bg,
                      outline,
                      outlineOffset: -2,
                      cursor: 'pointer',
                    }}
                  />
                );
              })}
            </>
          ))}
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: gridCols,
            gap: 2,
            fontSize: 10,
            opacity: 0.55,
            marginTop: 4,
          }}
        >
          <span />
          {heatmap.hours.map((h) => (
            <span key={h} style={{ textAlign: 'center' }}>
              {h % 2 === 0 ? Math.floor(h) : ''}
            </span>
          ))}
        </div>
      </div>

      <div
        style={{
          marginTop: 10,
          display: 'flex',
          gap: 8,
          flexWrap: 'wrap',
          fontSize: 11,
        }}
      >
        {(['free', 'light', 'moderate', 'heavy', 'jam'] as const).map((l) => (
          <Pill key={l} label={l} />
        ))}
      </div>

      {forecast && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 13, marginBottom: 8, opacity: 0.8 }}>
            Predicted state at {fmtTime(forecast.requested_hour)} · baseline{' '}
            {fmtTime(forecast.baseline_hour)}
          </div>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Approach</th>
                <th style={thStyle}>Pressure</th>
                <th style={thStyle}>Class</th>
                <th style={thStyle}>gmaps label</th>
                <th style={thStyle}>gmaps ratio</th>
                <th style={thStyle}>speed</th>
                <th style={thStyle}>scale vs now</th>
              </tr>
            </thead>
            <tbody>
              {(['S', 'N', 'E', 'W'] as const).map((a) => {
                const p = forecast.predicted[a];
                return (
                  <tr key={a}>
                    <td
                      style={{
                        ...tdStyle,
                        color: APPROACH_COLOR[a],
                        fontWeight: 700,
                      }}
                    >
                      {a}
                    </td>
                    <td style={tdStyle}>{p?.pressure ?? '-'}</td>
                    <td style={tdStyle}>
                      <Pill label={p?.label ?? '-'} />
                    </td>
                    <td style={tdStyle}>
                      <Pill label={p?.gmaps_label ?? '-'} />
                    </td>
                    <td style={tdStyle}>{p?.gmaps_congestion_ratio ?? '-'}</td>
                    <td style={tdStyle}>
                      {p?.gmaps_speed_kmh != null
                        ? `${p.gmaps_speed_kmh} km/h`
                        : '-'}
                    </td>
                    <td style={tdStyle}>{fmtScale(p?.scale_vs_now)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {forecast.recommendation?.comparison && (() => {
            const r = forecast.recommendation.comparison.recommended;
            const three = forecast.recommendation.mode === 'three_phase';
            return (
              <div style={{ marginTop: 10, fontSize: 13, opacity: 0.9 }}>
                Forecast Webster: cycle{' '}
                {forecast.recommendation.cycle_seconds.toFixed(1)}s · NS{' '}
                {r.NS_green.toFixed(1)}s
                {three ? (
                  <>
                    {' '}· E {(r.E_green ?? 0).toFixed(1)}s
                    {' '}· W {(r.W_green ?? 0).toFixed(1)}s
                  </>
                ) : (
                  <> · EW {(r.EW_green ?? 0).toFixed(1)}s</>
                )}
                {' '}· delay reduction{' '}
                {forecast.recommendation.comparison.delay_reduction_pct == null
                  ? '-'
                  : `${forecast.recommendation.comparison.delay_reduction_pct}%`}
              </div>
            );
          })()}
        </div>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Panel 6: Rolling N-hour forecast
// ─────────────────────────────────────────────────────────────
function RollingForecastPanel() {
  const [start, setStart] = useState<number>(10);
  const [hours, setHours] = useState<number>(12);
  const [data, setData] = useState<HorizonResp | null>(null);
  const [meta, setMeta] = useState<string>('');

  const run = useCallback(async () => {
    setMeta('loading…');
    try {
      const r = await fetch(
        apiUrl(`/api/forecast/horizon?start=${start}&hours=${hours}&step=0.5`),
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as HorizonResp;
      setData(j);
      setMeta(
        `${j.ticks.length} ticks from ${fmtTime(j.start_hour)} for ${j.hours}h (gmaps baseline ${fmtTime(j.baseline_hour)})`,
      );
    } catch (e) {
      setMeta(`error: ${(e as Error).message}`);
    }
  }, [start, hours]);

  // Seed from /api/heatmap current_hour once, then run initial.
  useEffect(() => {
    let alive = true;
    getHeatmap()
      .then((d) => {
        if (!alive) return;
        setStart(d.current_hour);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Auto-run when start changes (seeded) or on mount after 1.2s
  useEffect(() => {
    const id = window.setTimeout(() => run(), 200);
    return () => window.clearTimeout(id);
    // run depends on start/hours; re-run whenever start changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start]);

  const summary = useMemo(() => {
    if (!data) return null;
    const out: Record<
      Approach,
      {
        peak: string | null;
        peakHour: number | null;
        maxP: number | null;
        heavyPlus: number;
        freeCnt: number;
      }
    > = {
      S: { peak: null, peakHour: null, maxP: null, heavyPlus: 0, freeCnt: 0 },
      N: { peak: null, peakHour: null, maxP: null, heavyPlus: 0, freeCnt: 0 },
      E: { peak: null, peakHour: null, maxP: null, heavyPlus: 0, freeCnt: 0 },
      W: { peak: null, peakHour: null, maxP: null, heavyPlus: 0, freeCnt: 0 },
    };
    for (const a of ['S', 'N', 'E', 'W'] as const) {
      for (const t of data.ticks) {
        const p = t.per_approach[a];
        if (!p) continue;
        const rank = p.label ? LABEL_RANK[p.label] ?? -1 : -1;
        const curRank = out[a].peak
          ? LABEL_RANK[out[a].peak!] ?? -1
          : -1;
        if (out[a].peak == null || rank > curRank) {
          out[a].peak = p.label;
          out[a].peakHour = t.hour;
        }
        if (p.pressure != null && (out[a].maxP == null || p.pressure > out[a].maxP!)) {
          out[a].maxP = p.pressure;
          out[a].peakHour = t.hour;
        }
        if (p.label && LABEL_RANK[p.label] >= LABEL_RANK.heavy)
          out[a].heavyPlus += 1;
        if (p.label === 'free') out[a].freeCnt += 1;
      }
    }
    return out;
  }, [data]);

  const nCols = data?.ticks.length ?? 0;
  const gridCols = `40px repeat(${nCols}, minmax(22px, 1fr))`;

  const cycleLine = data
    ? 'Webster cycle across horizon (first 8): ' +
      data.ticks
        .slice(0, 8)
        .map((t) => `${fmtTime(t.hour)}:${t.recommended?.cycle_seconds ?? '-'}s`)
        .join('   ')
    : '';

  return (
    <section style={cardStyle}>
      <h2 style={cardTitle}>Next-N hours rolling forecast (gmaps-driven)</h2>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginBottom: 10,
          flexWrap: 'wrap',
        }}
      >
        <label style={{ fontSize: 12, opacity: 0.8 }}>
          start{' '}
          <input
            type="number"
            min={0}
            max={23.5}
            step={0.5}
            value={start}
            onChange={(e) => setStart(parseFloat(e.target.value))}
            style={{
              width: 70,
              background: '#0b0f14',
              color: '#e6edf3',
              border: '1px solid #1e2630',
              borderRadius: 4,
              padding: 4,
            }}
          />
        </label>
        <label style={{ fontSize: 12, opacity: 0.8 }}>
          horizon{' '}
          <input
            type="number"
            min={1}
            max={24}
            step={1}
            value={hours}
            onChange={(e) => setHours(parseFloat(e.target.value))}
            style={{
              width: 60,
              background: '#0b0f14',
              color: '#e6edf3',
              border: '1px solid #1e2630',
              borderRadius: 4,
              padding: 4,
            }}
          />{' '}
          h
        </label>
        <button
          onClick={run}
          style={{
            background: '#1f2937',
            color: '#e6edf3',
            border: '1px solid #2d3748',
            borderRadius: 6,
            padding: '6px 14px',
            cursor: 'pointer',
          }}
        >
          Forecast
        </button>
        <span style={{ opacity: 0.6, fontSize: 12 }}>{meta}</span>
      </div>

      {data && (
        <>
          <div style={{ overflowX: 'auto' }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: gridCols,
                gap: 2,
                minWidth: 900,
              }}
            >
              {(['S', 'N', 'E', 'W'] as const).map((a) => (
                <>
                  <div
                    key={`hz-lbl-${a}`}
                    style={{
                      fontWeight: 700,
                      fontSize: 14,
                      color: APPROACH_COLOR[a],
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      paddingRight: 6,
                    }}
                  >
                    {a}
                  </div>
                  {data.ticks.map((t) => {
                    const p = t.per_approach[a];
                    const bg = p?.label
                      ? LABEL_BG[p.label] ?? '#1e2630'
                      : '#1e2630';
                    const title = `${fmtTime(t.hour)} | ${p?.label ?? '-'} | p=${p?.pressure ?? '-'} | gmaps=${p?.gmaps_label ?? '-'} r=${p?.gmaps_ratio ?? '-'} | scale=${fmtScale(p?.scale_vs_now)}`;
                    return (
                      <div
                        key={`${a}-${t.hour}`}
                        title={title}
                        style={{ height: 22, borderRadius: 2, background: bg }}
                      />
                    );
                  })}
                </>
              ))}
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: gridCols,
                gap: 2,
                fontSize: 10,
                opacity: 0.55,
                marginTop: 4,
              }}
            >
              <span />
              {data.ticks.map((t, i) => (
                <span key={t.hour} style={{ textAlign: 'center' }}>
                  {i % 2 === 0 ? fmtTime(t.hour) : ''}
                </span>
              ))}
            </div>
          </div>

          <div style={{ marginTop: 10, fontSize: 12, opacity: 0.8 }}>
            {cycleLine}
          </div>

          {summary && (
            <div style={{ marginTop: 10 }}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>Approach</th>
                    <th style={thStyle}>Peak class</th>
                    <th style={thStyle}>Peak hour</th>
                    <th style={thStyle}>Max pressure</th>
                    <th style={thStyle}>Hours heavy+</th>
                    <th style={thStyle}>Hours free</th>
                  </tr>
                </thead>
                <tbody>
                  {(['S', 'N', 'E', 'W'] as const).map((a) => {
                    const s = summary[a];
                    return (
                      <tr key={a}>
                        <td
                          style={{
                            ...tdStyle,
                            color: APPROACH_COLOR[a],
                            fontWeight: 700,
                          }}
                        >
                          {a}
                        </td>
                        <td style={tdStyle}>
                          <Pill label={s.peak ?? '-'} />
                        </td>
                        <td style={tdStyle}>
                          {s.peakHour != null ? fmtTime(s.peakHour) : '-'}
                        </td>
                        <td style={tdStyle}>
                          {s.maxP != null ? s.maxP.toFixed(2) : '-'}
                        </td>
                        <td style={tdStyle}>{s.heavyPlus}</td>
                        <td style={tdStyle}>{s.freeCnt}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Panel 7a: Model forecast vs gmaps-anchored forecast
// ─────────────────────────────────────────────────────────────
interface ForecastCompareResp {
  horizons_min: number[];
  baseline_hour: number;
  model_type: string;
  model_trained_at: string | null;
  per_approach: Record<Approach, { ml: number[]; gmaps: number[] }>;
  agreement: Record<Approach, {
    mean_abs_diff_veh_per_15min: number;
    ml_mean: number;
    gmaps_mean: number;
  }>;
}

function ForecastVsGmapsPanel() {
  const [data, setData] = useState<ForecastCompareResp | null>(null);
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const r = await fetch(apiUrl('/api/forecast/compare'));
        if (!r.ok) return;
        const j = (await r.json()) as ForecastCompareResp;
        if (alive) setData(j);
      } catch {
        /* ignore */
      }
    };
    poll();
    const id = window.setInterval(poll, 30_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (!data) {
    return (
      <section style={cardStyle}>
        <h2 style={cardTitle}>Model forecast vs gmaps — per approach</h2>
        <div style={{ opacity: 0.6 }}>loading…</div>
      </section>
    );
  }

  const xLabels = data.horizons_min.map((h) => (h === 0 ? 'now' : `+${h}m`));

  return (
    <section style={cardStyle}>
      <h2 style={cardTitle}>Model forecast vs gmaps · per approach</h2>
      <div
        style={{
          display: 'flex',
          gap: 14,
          fontSize: 11,
          opacity: 0.75,
          marginBottom: 8,
          flexWrap: 'wrap',
        }}
      >
        <span>
          <span style={{ display: 'inline-block', width: 12, height: 2, background: '#86efac', marginRight: 6 }} />
          LightGBM (trained on detector counts)
        </span>
        <span>
          <span style={{ display: 'inline-block', width: 12, height: 2, background: '#fdba74', marginRight: 6, borderTop: '1px dashed #fdba74' }} />
          Gmaps-anchored (typical-Sunday corridor index, ratio → veh/15-min heuristic)
        </span>
        <span style={{ marginLeft: 'auto' }}>
          baseline hour {data.baseline_hour} · {data.model_type}
        </span>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 10,
        }}
      >
        {(['S', 'N', 'E', 'W'] as const).map((a) => {
          const series = [
            { key: `${a}-ml`, color: '#86efac', values: data.per_approach[a].ml, label: 'LightGBM' },
            { key: `${a}-gm`, color: '#fdba74', values: data.per_approach[a].gmaps, label: 'gmaps' },
          ];
          const ag = data.agreement[a];
          return (
            <div
              key={a}
              style={{
                background: '#0b0f14',
                border: '1px solid #1e2630',
                borderRadius: 8,
                padding: 10,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 8,
                  marginBottom: 4,
                }}
              >
                <strong style={{ color: APPROACH_COLOR[a], fontSize: 16 }}>{a}</strong>
                <span style={{ fontSize: 11, opacity: 0.7 }}>
                  approach
                </span>
              </div>
              <LineChart
                series={series}
                xLabels={xLabels}
                yLabel="veh/15min"
                width={360}
                height={160}
                xEvery={1}
              />
              <div
                style={{
                  marginTop: 4,
                  fontSize: 11,
                  opacity: 0.75,
                  display: 'flex',
                  gap: 10,
                  flexWrap: 'wrap',
                }}
              >
                <span>ml avg: <strong>{ag.ml_mean.toFixed(1)}</strong></span>
                <span>gm avg: <strong>{ag.gmaps_mean.toFixed(1)}</strong></span>
                <span>|Δ|: <strong>{ag.mean_abs_diff_veh_per_15min.toFixed(1)}</strong></span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Panel 7b: Model accuracy — LightGBM vs persistence baseline MAE per horizon
// ─────────────────────────────────────────────────────────────
interface ForecastMlMetrics {
  available: boolean;
  model_type?: string;
  trained_at?: string;
  n_train?: number;
  n_val?: number;
  baseline_mae?: { y_now: number; y_15min: number; y_30min: number; y_60min: number };
  lightgbm_mae?: { y_now: number; y_15min: number; y_30min: number; y_60min: number };
}

function ForecastAccuracyPanel() {
  const [m, setM] = useState<ForecastMlMetrics | null>(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch(apiUrl('/api/forecast/ml/metrics'));
        if (!r.ok) return;
        const j = (await r.json()) as ForecastMlMetrics;
        if (alive) setM(j);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const horizons: Array<keyof NonNullable<ForecastMlMetrics['baseline_mae']>> = [
    'y_now', 'y_15min', 'y_30min', 'y_60min',
  ];
  const horizonLabels: Record<string, string> = {
    y_now: 'now',
    y_15min: '+15m',
    y_30min: '+30m',
    y_60min: '+60m',
  };

  if (!m?.available) {
    return (
      <section style={cardStyle}>
        <h2 style={cardTitle}>Forecast accuracy · LightGBM vs persistence</h2>
        <div style={{ opacity: 0.6 }}>
          {m === null ? 'loading…' : 'metrics unavailable — train the model first'}
        </div>
      </section>
    );
  }

  const maxMae = Math.max(
    ...horizons.map((h) => m.baseline_mae?.[h] ?? 0),
    ...horizons.map((h) => m.lightgbm_mae?.[h] ?? 0),
    1,
  );

  return (
    <section style={cardStyle}>
      <h2 style={cardTitle}>Forecast accuracy · LightGBM vs persistence baseline</h2>
      <div
        style={{
          display: 'flex',
          gap: 16,
          fontSize: 11,
          opacity: 0.75,
          marginBottom: 10,
          flexWrap: 'wrap',
        }}
      >
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              background: '#86efac',
              marginRight: 6,
            }}
          />
          LightGBM (ours)
        </span>
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              background: '#fdba74',
              marginRight: 6,
            }}
          />
          Persistence baseline
        </span>
        <span style={{ marginLeft: 'auto' }}>
          trained on {m.n_train?.toLocaleString()} samples · validated on {m.n_val?.toLocaleString()} ·
          MAE lower is better (veh / 15 min)
        </span>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${horizons.length}, 1fr)`,
          gap: 12,
        }}
      >
        {horizons.map((h) => {
          const base = m.baseline_mae?.[h] ?? 0;
          const ml = m.lightgbm_mae?.[h] ?? 0;
          const reduction = base > 0 ? Math.round(((base - ml) / base) * 100) : 0;
          return (
            <div key={h} style={{ padding: 8 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  justifyContent: 'space-between',
                  fontSize: 12,
                  marginBottom: 6,
                }}
              >
                <strong>{horizonLabels[h]}</strong>
                <span style={{ color: '#86efac', fontWeight: 600 }}>
                  −{reduction}% MAE
                </span>
              </div>
              {/* LightGBM bar */}
              <MaeBar
                value={ml}
                maxValue={maxMae}
                color="#86efac"
                label={`LightGBM ${ml.toFixed(2)}`}
              />
              {/* Baseline bar */}
              <MaeBar
                value={base}
                maxValue={maxMae}
                color="#fdba74"
                label={`baseline ${base.toFixed(2)}`}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}

function MaeBar({
  value,
  maxValue,
  color,
  label,
}: {
  value: number;
  maxValue: number;
  color: string;
  label: string;
}) {
  const pct = Math.max(1, Math.min(100, (value / maxValue) * 100));
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginTop: 4,
        fontSize: 11,
      }}
    >
      <div
        style={{
          flex: 1,
          height: 10,
          background: '#1e2630',
          borderRadius: 3,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${pct}%`,
            background: color,
            transition: 'width .3s ease',
          }}
        />
      </div>
      <span style={{ opacity: 0.85, minWidth: 140 }}>{label}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Panel 7: Prediction charts + chart analysis
// ─────────────────────────────────────────────────────────────
function ForecastChartsPanel() {
  const [data, setData] = useState<Demand15MinResp | null>(null);

  useEffect(() => {
    let alive = true;
    const fetch15 = async () => {
      try {
        const r = await fetch(
          apiUrl('/api/forecast/demand_15min?lookback_bins=8'),
        );
        if (!r.ok) return;
        const j = (await r.json()) as Demand15MinResp;
        if (alive) setData(j);
      } catch {
        /* ignore */
      }
    };
    fetch15();
    const id = window.setInterval(fetch15, 30_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const { series, xLabels, analysis } = useMemo(() => {
    if (!data)
      return { series: [], xLabels: [] as string[], analysis: null as ReturnType<typeof buildAnalysis> | null };
    // Aggregate ML forecast per approach (sum across detectors sharing an approach).
    const fcByApproach: Record<Approach, number[]> = { S: [0,0,0,0], N: [0,0,0,0], E: [0,0,0,0], W: [0,0,0,0] };
    const perDet = data.forecast.per_detector ?? {};
    for (const rec of Object.values(perDet)) {
      if (!rec || !rec.approach) continue;
      const a = rec.approach as Approach;
      if (!fcByApproach[a]) continue;
      fcByApproach[a][0] += rec.y_now ?? 0;
      fcByApproach[a][1] += rec.y_15min ?? 0;
      fcByApproach[a][2] += rec.y_30min ?? 0;
      fcByApproach[a][3] += rec.y_60min ?? 0;
    }
    // Build combined series: history + forecast.
    const allApproaches: Approach[] = ['S', 'N', 'E', 'W'];
    const histBuckets = data.history[allApproaches[0]] ?? [];
    const histLabels = histBuckets.map((b) => b.bucket_start.slice(11, 16));
    const fcLabels = ['+0', '+15', '+30', '+60'];
    const xLabels = [...histLabels, ...fcLabels];
    const series = allApproaches.map((a) => {
      const hist = (data.history[a] ?? []).map((b) => b.count);
      const fc = fcByApproach[a] ?? [0, 0, 0, 0];
      return {
        key: a,
        color: APPROACH_COLOR[a],
        values: [...hist, ...fc],
        label: a,
      };
    });
    return { series, xLabels, analysis: buildAnalysis(data, fcByApproach) };
  }, [data]);

  return (
    <section style={cardStyle}>
      <h2 style={cardTitle}>Prediction charts · 15-min demand + ML forecast</h2>
      {data ? (
        <>
          <div
            style={{
              display: 'flex',
              gap: 14,
              fontSize: 11,
              flexWrap: 'wrap',
              marginBottom: 6,
              color: 'var(--fg-dim)',
              opacity: 0.8,
            }}
          >
            {(['S', 'N', 'E', 'W'] as const).map((a) => (
              <span key={a} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  style={{
                    width: 10,
                    height: 2,
                    background: APPROACH_COLOR[a],
                    display: 'inline-block',
                  }}
                />
                <span style={{ color: APPROACH_COLOR[a], fontWeight: 600 }}>{a}</span>
              </span>
            ))}
            <span style={{ marginLeft: 'auto' }}>
              Left of "+0": observed 15-min bins · Right: LightGBM forecast
              +0/+15/+30/+60 min (sum across detectors per approach)
            </span>
          </div>
          <LineChart
            series={series}
            xLabels={xLabels}
            yLabel="veh / 15-min"
            height={260}
          />
          {analysis && <ChartAnalysisStrip a={analysis} />}
        </>
      ) : (
        <div style={{ opacity: 0.6 }}>loading…</div>
      )}
    </section>
  );
}

function buildAnalysis(
  data: Demand15MinResp,
  fcByApproach: Record<Approach, number[]>,
) {
  const trend: Record<Approach, 'up' | 'down' | 'steady'> = {
    S: 'steady', N: 'steady', E: 'steady', W: 'steady',
  };
  for (const a of ['S', 'N', 'E', 'W'] as const) {
    const hist = (data.history[a] ?? []).map((b) => b.count);
    if (hist.length < 4) continue;
    const half = Math.floor(hist.length / 2);
    const prev = hist.slice(0, half).reduce((s, v) => s + v, 0) / Math.max(1, half);
    const recent = hist.slice(half).reduce((s, v) => s + v, 0) / Math.max(1, hist.length - half);
    const delta = recent - prev;
    if (Math.abs(delta) < Math.max(1, prev * 0.15)) trend[a] = 'steady';
    else if (delta > 0) trend[a] = 'up';
    else trend[a] = 'down';
  }
  // Peak forecast horizon per approach.
  const peak: Record<Approach, { value: number; horizon: string }> = {
    S: { value: 0, horizon: '+0' },
    N: { value: 0, horizon: '+0' },
    E: { value: 0, horizon: '+0' },
    W: { value: 0, horizon: '+0' },
  };
  const horizons = ['+0', '+15', '+30', '+60'];
  for (const a of ['S', 'N', 'E', 'W'] as const) {
    const fc = fcByApproach[a] ?? [];
    let maxVal = -Infinity;
    let maxIdx = 0;
    fc.forEach((v, i) => {
      if (v > maxVal) { maxVal = v; maxIdx = i; }
    });
    peak[a] = { value: maxVal, horizon: horizons[maxIdx] };
  }
  return { trend, peak };
}

function ChartAnalysisStrip({
  a,
}: {
  a: { trend: Record<Approach, 'up' | 'down' | 'steady'>; peak: Record<Approach, { value: number; horizon: string }> };
}) {
  return (
    <div
      style={{
        marginTop: 12,
        padding: 10,
        background: '#0b0f14',
        border: '1px solid #1e2630',
        borderRadius: 8,
        fontSize: 12,
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 10,
      }}
    >
      {(['S', 'N', 'E', 'W'] as const).map((app) => {
        const trend = a.trend[app];
        const trendIcon = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→';
        const trendColor = trend === 'up' ? '#fdba74' : trend === 'down' ? '#86efac' : '#e6edf3';
        const peak = a.peak[app];
        return (
          <div
            key={app}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              padding: 8,
              border: '1px solid #1e2630',
              borderRadius: 6,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
              <strong style={{ color: APPROACH_COLOR[app], fontSize: 14 }}>
                {app}
              </strong>
              <span style={{ color: trendColor, fontSize: 14, fontWeight: 700 }}>
                {trendIcon}
              </span>
              <span style={{ opacity: 0.7, fontSize: 11 }}>
                trend {trend}
              </span>
            </div>
            <div style={{ opacity: 0.85 }}>
              peak fc:{' '}
              <strong>{peak.value.toFixed(1)}</strong>
              <span style={{ opacity: 0.6 }}> veh @ {peak.horizon} min</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}


function ApproachZoneToggleAndEditor() {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          background: 'transparent',
          color: '#94a3b8',
          border: '1px dashed #1e293b',
          borderRadius: 8,
          padding: '6px 12px',
          marginBottom: 10,
          cursor: 'pointer',
          fontSize: 11,
          letterSpacing: 0.4,
          textAlign: 'left',
          width: '100%',
        }}
        title="Edit the outer S/N/E/W approach polygons"
      >
        ✎ Edit approach zones (outer polygons) — currently hardcoded; click to redraw
      </button>
    );
  }
  return <ApproachZoneEditor onClose={() => setOpen(false)} />;
}
