import { useEffect, useMemo, useRef, useState } from 'react';
import styles from './VideoPage.module.css';
import stStyles from './SignalTimingPage.module.css';
import { TimeSlider } from '../components/TimeSlider';
import { DayHeatmap } from '../components/DayHeatmap';
import { HistoricalPanel } from '../components/HistoricalPanel';
import { SystemHealthPanel } from '../components/SystemHealthPanel';
import {
  DEFAULT_PHASE_PLAN,
  fetchForecast,
  fetchOptimize,
  PHASE_NAMES,
  type ForecastRow,
  type OptimizeResponse,
  type PhaseNumber,
} from '../api/forecast';

const PHASE_ORDER: PhaseNumber[] = [2, 6, 4, 8];

interface CrossingEvent {
  timestamp: string;
  approach: string;
  delta?: number;
  in_count?: number;
  out_count?: number;
}

interface LaneCount {
  lane_id:   string;
  lane_type: string;
  lane_idx:  number;
  in:        number;
  out:       number;
}

interface CrossingsResponse {
  available: boolean;
  message?: string;
  per_approach_totals: Record<'N' | 'S' | 'E' | 'W', { in: number; out: number }>;
  per_approach_window: Record<'N' | 'S' | 'E' | 'W', { in: number; out: number }>;
  per_approach_lanes:  Record<'N' | 'S' | 'E' | 'W', LaneCount[]>;
  per_approach_current_occupancy: Record<'N' | 'S' | 'E' | 'W', number>;
  occupancy_latest_ts?: string;
  window_s: number;
  recent: CrossingEvent[];
  total_events_seen: number;
  total_lanes_tracked: number;
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}

interface GmapsNowResponse {
  available: boolean;
  message?: string;
  source_file?: string;
  amman_hhmm?: string;
  per_approach?: Record<
    'N' | 'S' | 'E' | 'W',
    { ratio: number | null; speed_kmh: number | null; label: string; street: string | null }
  >;
}

export function VideoPage() {
  // ── Live feed ──
  const [liveSrc, setLiveSrc] = useState<string>('/ai-thumb.jpg?ts=0');
  const [clock, setClock] = useState<string>('—');
  const [crossings, setCrossings] = useState<CrossingsResponse | null>(null);
  const [gmapsNow, setGmapsNow] = useState<GmapsNowResponse | null>(null);

  // ── Signal-timing sim (auto — user can't tune manually any more) ──
  const [simTime, setSimTime] = useState('17:00');
  const [optData, setOptData] = useState<OptimizeResponse | null>(null);
  const [optLoading, setOptLoading] = useState(false);
  const [optError, setOptError] = useState<string | null>(null);
  const [dayForecast, setDayForecast] = useState<ForecastRow[]>([]);
  const debouncedTime = useDebounced(simTime, 120);

  const liveTimerRef = useRef<number | null>(null);
  const eventsTimerRef = useRef<number | null>(null);

  // Clock
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const two = (n: number) => String(n).padStart(2, '0');
      setClock(
        `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}  ${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`,
      );
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);

  // Poll live AI snapshot every 200ms
  useEffect(() => {
    const tick = () => setLiveSrc(`/ai-thumb.jpg?ts=${Date.now()}`);
    tick();
    liveTimerRef.current = window.setInterval(tick, 200);
    return () => {
      if (liveTimerRef.current !== null) {
        window.clearInterval(liveTimerRef.current);
      }
    };
  }, []);

  // Poll /api/phase2/crossings every 1.5s — server-side filter
  useEffect(() => {
    const fetchCrossings = async () => {
      try {
        const res = await fetch('/api/phase2/crossings');
        const j = (await res.json()) as CrossingsResponse;
        setCrossings(j);
      } catch {
        // ignore
      }
    };
    fetchCrossings();
    // 2.5s: server-side mtime cache already short-circuits repeat work, and
    // at 1.5s the browser was spending a full second every cycle parsing
    // the 5 KB response.
    eventsTimerRef.current = window.setInterval(fetchCrossings, 2500);
    return () => {
      if (eventsTimerRef.current !== null) {
        window.clearInterval(eventsTimerRef.current);
      }
    };
  }, []);

  // Poll /api/gmaps/now every 30s — current Amman-local typical-Sunday state
  useEffect(() => {
    const fetchNow = async () => {
      try {
        const res = await fetch('/api/gmaps/now');
        const j = (await res.json()) as GmapsNowResponse;
        setGmapsNow(j);
      } catch {
        // ignore
      }
    };
    fetchNow();
    const id = window.setInterval(fetchNow, 30_000);
    return () => window.clearInterval(id);
  }, []);

  // Fetch optimizer data whenever time changes. We pass NO green overrides
  // so the endpoint evaluates the current (default) plan AND emits Webster's
  // auto-recommendation — the user doesn't tune sliders any more.
  useEffect(() => {
    let cancelled = false;
    setOptLoading(true);
    fetchOptimize(debouncedTime)
      .then((d) => {
        if (!cancelled) {
          setOptData(d);
          setOptError(null);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setOptError(e.message);
      })
      .finally(() => {
        if (!cancelled) setOptLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedTime]);

  // Full-day forecast for the heatmap (48 slots × 4 approaches)
  useEffect(() => {
    fetchForecast()
      .then((d) => {
        if (d.available && d.rows) setDayForecast(d.rows);
      })
      .catch(() => undefined);
  }, []);

  const websterGreens: Record<PhaseNumber, number> = useMemo(() => {
    const out = { ...DEFAULT_PHASE_PLAN };
    const wg = optData?.webster?.green;
    if (wg) {
      for (const ph of PHASE_ORDER) {
        const v = wg[String(ph)];
        if (typeof v === 'number') out[ph] = v;
      }
    }
    return out;
  }, [optData]);

  const currentGreens: Record<PhaseNumber, number> = DEFAULT_PHASE_PLAN;

  const websterRowsByPhase = useMemo(() => {
    const rows = optData?.webster?.rows ?? [];
    const map: Partial<Record<PhaseNumber, typeof rows>> = {};
    for (const ph of PHASE_ORDER) map[ph] = [];
    for (const row of rows) {
      const bucket = map[row.phase];
      if (bucket) bucket.push(row);
    }
    return map;
  }, [optData]);

  const cycleWebster = optData?.webster?.cycle_s ?? 102;
  const cycleCurrent = 102;
  const currentDelay = optData?.current?.summary.weighted_avg_delay_s;
  const websterDelay = optData?.webster?.summary.weighted_avg_delay_s;
  const delayDelta = optData?.delay_reduction_pct;
  const Y = optData?.current?.critical_y;

  const advisories = (optData?.current?.rows ?? []).map((r) => ({
    key: `${r.approach}-${r.phase}`,
    text: `${r.approach} · ${PHASE_NAMES[r.phase]}: ${r.recommendation}`,
  }));

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <div>
          <h1 className={styles.brandTitle} style={{ margin: 0 }}>
            Live Feed
          </h1>
          <div style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)',
                        marginTop: 2, letterSpacing: '0.04em' }}>
            TheVideo.mp4 → 15 fps RTSP → YOLO26 + ByteTrack
          </div>
        </div>
        <div />
        <div className={styles.metaRight}>
          <time className={styles.clock}>{clock}</time>
        </div>
      </header>

      {/* LIVE FEED */}
      <section className={styles.panel}>
        <div className={styles.stage}>
          <div className={styles.stageChrome}>
            <span className={styles.tag}>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: 'var(--accent)',
                  display: 'inline-block',
                }}
              />
              LIVE · YOLO26X
            </span>
            <span className={styles.stageMeta}>
              TheVideo.mp4 → 15 fps RTSP → YOLO26X + ByteTrack + camera homography
            </span>
          </div>
          <img
            src={liveSrc}
            alt="Live YOLO26m annotated feed"
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'contain',
              display: 'block',
              background: '#000',
            }}
          />
        </div>
      </section>

      {/* APPROACH METRICS */}
      <section className={styles.panel}>
        <div className={styles.forecastHead} style={{ marginBottom: 12 }}>
          Cars at each stop · live
          <span>
            {' '}· Google time slot{' '}
            <b style={{ color: 'var(--fg-dim)' }}>
              {gmapsNow?.amman_hhmm ?? '—'}
            </b>{' '}
            Amman ·{' '}
            {crossings?.total_events_seen ?? 0} crossings logged
          </span>
        </div>
        <div className={styles.approachCards}>
          {(['N', 'S', 'E', 'W'] as const).map((a) => {
            const totals = crossings?.per_approach_totals[a] ?? { in: 0, out: 0 };
            const currentOcc = crossings?.per_approach_current_occupancy?.[a] ?? 0;
            const gmaps = gmapsNow?.per_approach?.[a];
            const label = gmaps?.label ?? 'unknown';
            const labelColor =
              label === 'free'
                ? 'var(--good)'
                : label === 'light'
                  ? 'var(--accent)'
                  : label === 'heavy'
                    ? '#D68F6B'
                    : label === 'jam'
                      ? 'var(--bad)'
                      : 'var(--fg-mute)';
            return (
              <div key={a} className={styles.ac}>
                <div className={styles.acAppr}>{a} approach</div>
                {/* Primary: live cars at stop */}
                <div className={styles.acCount}>
                  {currentOcc}
                  <span className={styles.u}>cars now</span>
                </div>
                {/* Google traffic state chip */}
                <div
                  style={{
                    marginTop: 8,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    font: '500 11px var(--mono)',
                    letterSpacing: '0.04em',
                  }}
                >
                  <span
                    style={{
                      width: 9,
                      height: 9,
                      borderRadius: '50%',
                      background: labelColor,
                      boxShadow: `0 0 6px ${labelColor}55`,
                      display: 'inline-block',
                    }}
                  />
                  <span style={{ color: labelColor, textTransform: 'uppercase' }}>
                    {label}
                  </span>
                  {gmaps?.ratio != null && (
                    <span style={{ color: 'var(--fg-mute)' }}>
                      · Google ratio {gmaps.ratio.toFixed(2)}×
                    </span>
                  )}
                </div>
                {gmaps?.street && (
                  <div
                    style={{
                      marginTop: 4,
                      font: '400 10px var(--mono)',
                      color: 'var(--fg-faint)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={gmaps.street}
                  >
                    {gmaps.street}
                  </div>
                )}
                {/* Cumulative crossings — secondary metric */}
                <div
                  style={{
                    marginTop: 10,
                    paddingTop: 8,
                    borderTop: '1px solid var(--border-soft)',
                    font: '400 11px var(--mono)',
                    color: 'var(--fg-dim)',
                  }}
                >
                  cumulative: <b style={{ color: 'var(--fg)' }}>{totals.in}</b> in ·{' '}
                  <b style={{ color: 'var(--fg)' }}>{totals.out}</b> out
                </div>
              </div>
            );
          })}
        </div>
        {(crossings?.recent?.length ?? 0) > 0 && (
          <div
            style={{
              marginTop: 12,
              padding: '10px 14px',
              background: 'var(--surface-2)',
              border: '1px solid var(--border-soft)',
              borderRadius: 'var(--r-sm)',
              font: '400 11px var(--mono)',
              color: 'var(--fg-dim)',
              maxHeight: 180,
              overflowY: 'auto',
            }}
          >
            {crossings!.recent.map((ev, i) => (
              <div
                key={`${ev.timestamp}-${i}`}
                style={{ lineHeight: 1.7, display: 'flex', gap: 10 }}
              >
                <span style={{ color: 'var(--fg-mute)', minWidth: 110 }}>
                  {ev.timestamp.slice(11, 23)}
                </span>
                <span
                  style={{
                    color: 'var(--accent)',
                    minWidth: 30,
                  }}
                >
                  {ev.approach}
                </span>
                <span>
                  Δ=<b style={{ color: 'var(--fg)' }}>{ev.delta ?? '—'}</b>
                  {'  '}cum in=
                  <b style={{ color: 'var(--fg)' }}>{ev.in_count ?? '—'}</b>
                  {'  '}out=
                  <b style={{ color: 'var(--fg)' }}>{ev.out_count ?? '—'}</b>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* DAY HEATMAP + AUTO WEBSTER */}
      <section className={stStyles.panel}>
        <div className={stStyles.panelHead}>
          <div>
            <h2 className={stStyles.panelTitle}>
              Day forecast → Webster auto-recommend
            </h2>
            <p className={stStyles.panelBasis}>
              Click a cell on the timeline below (or drag the slider) to any
              time of day. Top row shows Google's typical-Sunday congestion
              state per approach; the Webster + HCM optimiser then computes
              the best signal timings for that demand automatically —
              <b> no manual tuning</b>. Outputs are advisory only (Handbook §11).
            </p>
          </div>
          <span className={stStyles.panelHint}>/api/forecast/optimize</span>
        </div>

        {dayForecast.length > 0 && (
          <DayHeatmap
            rows={dayForecast}
            currentHhmm={simTime}
            onSelect={setSimTime}
          />
        )}

        <TimeSlider value={simTime} onChange={setSimTime} />

        {optError && (
          <div
            className={stStyles.advice}
            style={{
              color: 'var(--bad)',
              borderColor: 'rgba(228,111,111,0.4)',
            }}
          >
            API error: {optError}
          </div>
        )}

        <div className={stStyles.phaseGrid}>
          {PHASE_ORDER.map((ph) => {
            const websterRows = websterRowsByPhase[ph] ?? [];
            const currentG = currentGreens[ph];
            const websterG = websterGreens[ph];
            const delta = websterG - currentG;
            const worstWeb = websterRows.reduce<
              typeof websterRows[number] | undefined
            >(
              (acc, r) => (!acc || r.x > acc.x ? r : acc),
              undefined,
            );
            const sigClass =
              worstWeb?.signal_color === 'green'
                ? stStyles.sigGreen
                : worstWeb?.signal_color === 'yellow'
                  ? stStyles.sigYellow
                  : worstWeb?.signal_color === 'red'
                    ? stStyles.sigRed
                    : '';
            return (
              <div
                key={ph}
                className={`${stStyles.phase} ${sigClass}`}
              >
                <div className={stStyles.phaseTag}>Phase {ph}</div>
                <div className={stStyles.phaseName}>{PHASE_NAMES[ph]}</div>
                <div className={stStyles.gVal} style={{ marginTop: 10 }}>
                  {websterG}
                  <span className={stStyles.gValUnit}>s recommended</span>
                </div>
                <div
                  className={stStyles.phaseStats}
                  style={{ marginTop: 8 }}
                >
                  <div>
                    <span
                      style={{ color: 'var(--fg-faint)', marginRight: 6 }}
                    >
                      current plan:
                    </span>
                    {currentG}s
                    <span
                      style={{ color: 'var(--fg-mute)', marginLeft: 6 }}
                    >
                      ({delta >= 0 ? '+' : ''}{delta}s)
                    </span>
                  </div>
                  {websterRows.map((r) => (
                    <div
                      key={`${r.approach}-${r.phase}`}
                      style={{ color: 'var(--fg-dim)' }}
                    >
                      <span style={{ color: 'var(--fg-faint)', marginRight: 6 }}>
                        {r.approach}:
                      </span>
                      <span>v/c {r.x.toFixed(2)}</span>
                      <span style={{ color: 'var(--fg-mute)', margin: '0 6px' }}>
                        ·
                      </span>
                      <span>delay {r.delay_s.toFixed(0)}s</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        <div className={stStyles.toolbar}>
          <span className={stStyles.stat}>
            RECOMMENDED CYCLE <b>{cycleWebster}s</b>{' '}
            <span style={{ color: 'var(--fg-mute)' }}>
              (current plan {cycleCurrent}s)
            </span>
          </span>
          <span className={stStyles.stat}>
            Y <b>{Y?.toFixed(3) ?? '—'}</b>
          </span>
          <span className={stStyles.stat}>
            avg delay · current plan{' '}
            <b>{currentDelay?.toFixed(1) ?? '—'}s</b> → Webster{' '}
            <b>{websterDelay?.toFixed(1) ?? '—'}s</b>
          </span>
          {delayDelta !== undefined && (
            <span
              className={`${stStyles.pill} ${
                delayDelta > 0 ? stStyles.pillGood : stStyles.pillBad
              }`}
            >
              {delayDelta > 0
                ? `−${delayDelta.toFixed(1)}% delay`
                : `+${Math.abs(delayDelta).toFixed(1)}% delay`}
            </span>
          )}
          {optLoading && (
            <span style={{ color: 'var(--fg-mute)' }}>updating…</span>
          )}
        </div>

        {advisories.length > 0 && (
          <div className={stStyles.advice}>
            <b>§8.3 advisories</b>
            <ul>
              {advisories.map((a) => (
                <li key={a.key}>{a.text}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <HistoricalPanel />
      <SystemHealthPanel />

      <footer className={styles.footer}>
        Traffic Ops<span className={styles.sep}>/</span>SITE-001 · Amman
        <span className={styles.sep}>/</span>Phase 2 build · hackathon 2026
      </footer>
    </main>
  );
}
