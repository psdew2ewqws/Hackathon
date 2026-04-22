import { useEffect, useMemo, useState } from 'react';
import styles from './InfoPage.module.css';
import {
  LineChart, Heatmap, GroupedBars, ApproachLegend, APPROACH_COLOR, APPROACHES,
} from '../components/charts';
import {
  fetchForecast, fetchOptimize,
  type ForecastDay, type OptimizeResponse,
} from '../api/forecast';

// ── Types for the new /api/analysis/throughput endpoint ──────────
interface ThroughputResponse {
  available: boolean;
  message?: string;
  window_min?: number;
  bin_min?: number;
  latest_ts?: string;
  bin_labels?: string[];
  series?: Record<'N' | 'S' | 'E' | 'W', number[]>;
  totals?: Record<'N' | 'S' | 'E' | 'W', number>;
  grand_total?: number;
}

// ── Types for /api/history/counts ────────────────────────────────
interface HistoricalRow {
  hour: number;
  avg_count: number;
}
interface HistoricalResponse {
  available: boolean;
  message?: string;
  days?: number;
  first_date?: string;
  last_date?: string;
  per_approach_hourly?: Record<'N' | 'S' | 'E' | 'W', HistoricalRow[]>;
  total_rows?: number;
}

function hhmmTo24Slots(idx: number): string {
  const h = String(Math.floor(idx / 2)).padStart(2, '0');
  const m = idx % 2 === 0 ? '00' : '30';
  return `${h}:${m}`;
}

export function AnalysisPage() {
  // ── Chart 1: Live throughput (last 60 min) ─────────────────────
  const [throughput, setThroughput] = useState<ThroughputResponse | null>(null);
  const [windowMin, setWindowMin] = useState(60);
  const [binMin, setBinMin] = useState(5);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await fetch(
          `/api/analysis/throughput?window=${windowMin}&bin=${binMin}`,
        );
        const j = (await res.json()) as ThroughputResponse;
        if (!cancelled) setThroughput(j);
      } catch {
        /* swallow — next tick retries */
      }
    };
    tick();
    const id = window.setInterval(tick, 7000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [windowMin, binMin]);

  // ── Chart 2: 14-day historical pattern ─────────────────────────
  const [history, setHistory] = useState<HistoricalResponse | null>(null);
  useEffect(() => {
    fetch('/api/history/counts?days=14')
      .then((r) => r.json())
      .then((j) => setHistory(j as HistoricalResponse))
      .catch(() => undefined);
  }, []);

  // ── Chart 3: Today's forecast heatmap ──────────────────────────
  const [forecast, setForecast] = useState<ForecastDay | null>(null);
  useEffect(() => {
    fetchForecast().then(setForecast).catch(() => undefined);
  }, []);

  // ── Chart 4: Current plan vs Webster (user-picked time) ───────
  const [simTime, setSimTime] = useState('17:00');
  const [optimize, setOptimize] = useState<OptimizeResponse | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchOptimize(simTime)
      .then((d) => {
        if (!cancelled) setOptimize(d);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [simTime]);

  // Build heatmap cells from forecast rows
  const heatmapCells = useMemo(() => {
    const rows = forecast?.rows ?? [];
    const cells: Array<{
      approach: 'N' | 'S' | 'E' | 'W';
      slotIdx: number;
      label: string;
      value: number | null;
      hhmm: string;
    }> = [];
    for (const r of rows) {
      const [h, m] = r.time.split(':').map(Number);
      const slotIdx = h * 2 + (m >= 30 ? 1 : 0);
      cells.push({
        approach: r.approach,
        slotIdx,
        label: r.label,
        value: r.ratio,
        hhmm: r.time,
      });
    }
    return cells;
  }, [forecast]);

  const slotLabels = Array.from({ length: 48 }, (_, i) => hhmmTo24Slots(i));

  // Derived stats
  const totalCrossings = throughput?.grand_total ?? 0;
  const busiestApproach = useMemo(() => {
    if (!throughput?.totals) return null;
    const entries = Object.entries(throughput.totals);
    entries.sort((a, b) => b[1] - a[1]);
    return entries[0];
  }, [throughput]);

  // Webster bar series
  const websterRows = optimize?.webster?.rows ?? [];
  const currentRows = optimize?.current?.rows ?? [];
  const perApproachCurrent: Record<'N' | 'S' | 'E' | 'W', number> = {
    N: 0, S: 0, E: 0, W: 0,
  };
  const perApproachWebster: Record<'N' | 'S' | 'E' | 'W', number> = {
    N: 0, S: 0, E: 0, W: 0,
  };
  for (const r of currentRows) {
    perApproachCurrent[r.approach] = Math.max(
      perApproachCurrent[r.approach],
      r.delay_s,
    );
  }
  for (const r of websterRows) {
    perApproachWebster[r.approach] = Math.max(
      perApproachWebster[r.approach],
      r.delay_s,
    );
  }

  const delayDelta = optimize?.delay_reduction_pct;

  return (
    <main className={styles.page}>
      <header className={styles.head}>
        <div>
          <h1 className={styles.title}>Analysis</h1>
          <div className={styles.subtitle}>
            Four views that connect live detection, historical baseline, day
            forecast, and signal-timing recommendation.
          </div>
        </div>
        <div className={styles.headRight}>
          {throughput?.latest_ts
            ? `latest sample @ ${throughput.latest_ts}`
            : '—'}
        </div>
      </header>

      {/* Summary cards */}
      <div className={styles.summary}>
        <div className={styles.summaryCard}>
          <div className={styles.label}>Crossings last {windowMin}m</div>
          <div className={styles.value}>{totalCrossings.toLocaleString()}</div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.label}>Busiest approach</div>
          <div className={styles.value}
               style={{ color: busiestApproach ? APPROACH_COLOR[busiestApproach[0] as 'N'] : 'var(--fg)' }}>
            {busiestApproach ? `${busiestApproach[0]} · ${busiestApproach[1]}` : '—'}
          </div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.label}>History days loaded</div>
          <div className={styles.value}>{history?.days ?? '—'}</div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.label}>Δ delay vs Webster @ {simTime}</div>
          <div className={styles.value}
               style={{ color: delayDelta && delayDelta > 0 ? 'var(--good)' : 'var(--fg)' }}>
            {delayDelta != null
              ? (delayDelta > 0 ? `−${delayDelta.toFixed(1)}%` : `+${Math.abs(delayDelta).toFixed(1)}%`)
              : '—'}
          </div>
        </div>
      </div>

      {/* ═══ Chart 1 — Live throughput ═══ */}
      <section className={styles.panel}>
        <div style={{ display: 'flex', justifyContent: 'space-between',
                      alignItems: 'baseline', marginBottom: 14 }}>
          <div>
            <h2 style={{ font: '600 14px var(--sans)', margin: 0,
                         color: 'var(--fg)' }}>
              1 · Live throughput per approach
            </h2>
            <p style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)',
                        margin: '3px 0 0', letterSpacing: '0.02em' }}>
              Stop-line crossings bucketed into {binMin}-min bins — direct
              read of phase2.ndjson.
            </p>
          </div>
          <div className={styles.toolbar} style={{ margin: 0 }}>
            window:
            <select value={windowMin} onChange={(e) => setWindowMin(Number(e.target.value))}>
              <option value={30}>30 min</option>
              <option value={60}>60 min</option>
              <option value={120}>2 h</option>
              <option value={240}>4 h</option>
            </select>
            bin:
            <select value={binMin} onChange={(e) => setBinMin(Number(e.target.value))}>
              <option value={1}>1 min</option>
              <option value={5}>5 min</option>
              <option value={10}>10 min</option>
            </select>
          </div>
        </div>
        <ApproachLegend />
        {throughput?.available && throughput.bin_labels && throughput.series ? (
          <LineChart
            xLabels={throughput.bin_labels}
            series={APPROACHES.map((a) => ({
              key: a,
              color: APPROACH_COLOR[a],
              label: `${a} approach`,
              values: throughput.series![a] ?? [],
            }))}
            yLabel="crossings per bin"
          />
        ) : (
          <div className={styles.empty}>
            {throughput?.message ?? 'Loading throughput…'}
          </div>
        )}
      </section>

      {/* ═══ Chart 2 — 14-day hourly pattern ═══ */}
      <section className={styles.panel}>
        <div style={{ marginBottom: 14 }}>
          <h2 style={{ font: '600 14px var(--sans)', margin: 0,
                       color: 'var(--fg)' }}>
            2 · Typical daily pattern (14-day rolling avg)
          </h2>
          <p style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)',
                      margin: '3px 0 0', letterSpacing: '0.02em' }}>
            Hourly mean vehicle count per approach, averaged across the last
            {' '}{history?.days ?? '—'} days of detector counts.
            {history?.first_date && history?.last_date
              ? ` · ${history.first_date} → ${history.last_date}`
              : ''}
          </p>
        </div>
        <ApproachLegend />
        {history?.available && history.per_approach_hourly ? (() => {
          // Build aligned arrays indexed by hour-of-day (0..23).
          // Source rows are every 30 min, so aggregate to hourly.
          const hrs = Array.from({ length: 24 }, (_, h) => h);
          const xLabels = hrs.map((h) => `${String(h).padStart(2, '0')}:00`);
          const series = APPROACHES.map((a) => {
            const rows = history.per_approach_hourly![a] ?? [];
            const byHour = new Map<number, { s: number; n: number }>();
            for (const r of rows) {
              const h = Math.floor(r.hour);
              const cur = byHour.get(h) ?? { s: 0, n: 0 };
              cur.s += r.avg_count;
              cur.n += 1;
              byHour.set(h, cur);
            }
            return {
              key: a,
              color: APPROACH_COLOR[a],
              label: `${a} approach`,
              values: hrs.map((h) => {
                const c = byHour.get(h);
                return c ? c.s / c.n : 0;
              }),
            };
          });
          return (
            <LineChart
              xLabels={xLabels}
              series={series}
              yLabel="avg vehicles / hour"
              xEvery={3}
            />
          );
        })() : (
          <div className={styles.empty}>
            {history?.message ?? 'Loading history…'}
          </div>
        )}
      </section>

      {/* ═══ Chart 3 — Day forecast heatmap ═══ */}
      <section className={styles.panel}>
        <div style={{ marginBottom: 14 }}>
          <h2 style={{ font: '600 14px var(--sans)', margin: 0,
                       color: 'var(--fg)' }}>
            3 · Today's congestion forecast (4 approaches × 48 slots)
          </h2>
          <p style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)',
                      margin: '3px 0 0', letterSpacing: '0.02em' }}>
            BPR-scaled anchor video × Google typical-day curve. Hover a cell
            for the exact ratio.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap',
                      font: '500 10px var(--mono)', color: 'var(--fg-dim)',
                      marginBottom: 8, letterSpacing: '0.04em' }}>
          {(['free', 'light', 'heavy', 'jam', 'unknown'] as const).map((lab) => (
            <span key={lab} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                display: 'inline-block', width: 10, height: 10, borderRadius: 2,
                background: lab === 'free' ? '#7FA889'
                  : lab === 'light' ? '#E8B464'
                    : lab === 'heavy' ? '#D68F6B'
                      : lab === 'jam' ? '#B85450'
                        : '#2A2D35',
              }} />
              {lab}
            </span>
          ))}
        </div>
        {forecast?.available && heatmapCells.length > 0 ? (
          <Heatmap cells={heatmapCells} slotLabels={slotLabels} />
        ) : (
          <div className={styles.empty}>
            {forecast?.message ?? 'Loading forecast…'}
          </div>
        )}
      </section>

      {/* ═══ Chart 4 — Current vs Webster delay ═══ */}
      <section className={styles.panel}>
        <div style={{ display: 'flex', justifyContent: 'space-between',
                      alignItems: 'baseline', marginBottom: 14 }}>
          <div>
            <h2 style={{ font: '600 14px var(--sans)', margin: 0,
                         color: 'var(--fg)' }}>
              4 · Current plan vs Webster-optimal @ <b style={{ color: 'var(--accent)' }}>{simTime}</b>
            </h2>
            <p style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)',
                        margin: '3px 0 0', letterSpacing: '0.02em' }}>
              Per-approach max delay-seconds under each signal plan. HCM Ch.18
              delay model; Webster cycle per §7.5.
            </p>
          </div>
          <div className={styles.toolbar} style={{ margin: 0 }}>
            time:
            <input type="time" value={simTime}
                   onChange={(e) => setSimTime(e.target.value || '17:00')}
                   step={1800} />
          </div>
        </div>
        {optimize?.available && currentRows.length > 0 ? (
          <GroupedBars
            categories={APPROACHES as unknown as string[]}
            seriesA={{
              label: `Current plan (cycle ${optimize.current?.cycle_s ?? '—'}s)`,
              color: '#9097A0',
              values: APPROACHES.map((a) => perApproachCurrent[a]),
            }}
            seriesB={{
              label: `Webster (cycle ${optimize.webster?.cycle_s ?? '—'}s)`,
              color: '#E8B464',
              values: APPROACHES.map((a) => perApproachWebster[a]),
            }}
            yLabel="max delay (s)"
            unit="s"
          />
        ) : (
          <div className={styles.empty}>
            {optimize?.message ?? 'Loading optimizer…'}
          </div>
        )}
      </section>
    </main>
  );
}
