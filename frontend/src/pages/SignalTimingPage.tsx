import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import styles from './SignalTimingPage.module.css';
import { TimeSlider } from '../components/TimeSlider';
import { PhaseCard } from '../components/PhaseCard';
import {
  DEFAULT_PHASE_PLAN,
  fetchOptimize,
  PHASE_NAMES,
  type OptimizeResponse,
  type PhaseNumber,
} from '../api/forecast';

const PHASE_ORDER: PhaseNumber[] = [2, 6, 4, 8];

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}

export function SignalTimingPage() {
  const [time, setTime] = useState('17:00');
  const [greens, setGreens] = useState<Record<PhaseNumber, number>>({
    ...DEFAULT_PHASE_PLAN,
  });
  const [data, setData] = useState<OptimizeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Debounce slider changes so we don't hammer the API while dragging
  const debouncedTime = useDebounced(time, 120);
  const debouncedGreens = useDebounced(greens, 180);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOptimize(debouncedTime, debouncedGreens)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedTime, debouncedGreens]);

  // Group current eval rows by phase so each PhaseCard shows its 2 approaches
  const rowsByPhase = useMemo(() => {
    const rows = data?.current?.rows ?? [];
    const map: Partial<Record<PhaseNumber, typeof rows>> = {};
    for (const ph of PHASE_ORDER) map[ph] = [];
    for (const row of rows) {
      const bucket = map[row.phase];
      if (bucket) bucket.push(row);
    }
    return map;
  }, [data]);

  const applyWebster = useCallback(() => {
    if (!data?.webster?.green) return;
    const next: Record<PhaseNumber, number> = { ...DEFAULT_PHASE_PLAN };
    for (const ph of PHASE_ORDER) {
      const key = String(ph);
      if (data.webster.green[key] !== undefined) {
        next[ph] = data.webster.green[key];
      }
    }
    setGreens(next);
  }, [data]);

  const resetToPlan = useCallback(() => {
    setGreens({ ...DEFAULT_PHASE_PLAN });
  }, []);

  const setPhaseGreen = useCallback((phase: PhaseNumber, g: number) => {
    setGreens((prev) => ({ ...prev, [phase]: g }));
  }, []);

  const cycleTotal = useMemo(
    () =>
      PHASE_ORDER.reduce((acc, ph) => acc + greens[ph], 0) + 20, // +L
    [greens],
  );
  const cycleOk = cycleTotal >= 60 && cycleTotal <= 120;

  const currentDelay = data?.current?.summary.weighted_avg_delay_s;
  const websterDelay = data?.webster?.summary.weighted_avg_delay_s;
  const delayDelta = data?.delay_reduction_pct;
  const Y = data?.current?.critical_y;

  const advisories = (data?.current?.rows ?? []).map((r) => ({
    key: `${r.approach}-${r.phase}`,
    text: `${r.approach} · ${PHASE_NAMES[r.phase]}: ${r.recommendation}`,
  }));

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <div className={styles.brandLogo} aria-hidden="true" />
          <h1 className={styles.brandTitle}>
            Traffic Ops<span className={styles.sep}>/</span>
            <span className={styles.site}>Signal Timing Simulator</span>
          </h1>
        </div>
        <div />
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <Link
            to="/system"
            style={{
              font: '500 11px var(--mono)',
              color: 'var(--fg-dim)',
              textDecoration: 'none',
              padding: '4px 10px',
              border: '1px solid var(--border)',
              borderRadius: 999,
              letterSpacing: '0.02em',
            }}
          >
            System
          </Link>
          <Link to="/" className={styles.backLink}>
            ← Dashboard
          </Link>
        </div>
      </header>

      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <div>
            <h2 className={styles.panelTitle}>
              Webster + HCM what-if simulator
            </h2>
            <p className={styles.panelBasis}>
              Inputs at <b>{time}</b> (Amman local): drive from the forecast
              anchor, calibrated against the Google typical-day curve.
              Algorithm: Webster 1958 optimal cycle + HCM Ch. 18 delay.
              <br />
              Outputs are <b>advisory only</b> (Handbook §11) — no signal
              controller is modified.
            </p>
          </div>
          <span className={styles.panelHint}>/api/forecast/optimize</span>
        </div>

        <TimeSlider value={time} onChange={setTime} />

        {error && (
          <div
            className={styles.advice}
            style={{ color: 'var(--bad)', borderColor: 'rgba(228,111,111,0.4)' }}
          >
            API error: {error}
          </div>
        )}

        <div className={styles.phaseGrid}>
          {PHASE_ORDER.map((ph) => (
            <PhaseCard
              key={ph}
              phase={ph}
              greenSeconds={greens[ph]}
              rows={rowsByPhase[ph] ?? []}
              websterRecommended={
                data?.webster?.green?.[String(ph)]
                  ? Number(data.webster.green[String(ph)])
                  : undefined
              }
              onChange={setPhaseGreen}
            />
          ))}
        </div>

        <div className={styles.toolbar}>
          <span className={styles.stat}>
            CYCLE <b>{cycleTotal}s</b>{' '}
            <span
              className={`${styles.pill} ${cycleOk ? styles.pillGood : styles.pillBad}`}
            >
              {cycleOk ? 'in range' : 'out of 60–120s'}
            </span>
          </span>
          <span className={styles.stat}>
            Y <b>{Y?.toFixed(3) ?? '—'}</b>
          </span>
          <span className={styles.stat}>
            avg delay <b>{currentDelay?.toFixed(1) ?? '—'}s</b>{' '}
            vs Webster <b>{websterDelay?.toFixed(1) ?? '—'}s</b>
          </span>
          {delayDelta !== undefined && (
            <span
              className={`${styles.pill} ${
                delayDelta > 0 ? styles.pillGood : styles.pillBad
              }`}
            >
              {delayDelta > 0 ? `−${delayDelta.toFixed(1)}%` : `${delayDelta.toFixed(1)}%`}{' '}
              Δdelay
            </span>
          )}
          <span style={{ flex: 1 }} />
          <button onClick={applyWebster} disabled={!data?.webster}>
            Webster Recommend
          </button>
          <button className="ghost" onClick={resetToPlan}>
            Reset to plan
          </button>
          {loading && (
            <span style={{ color: 'var(--fg-mute)' }}>updating…</span>
          )}
        </div>

        {advisories.length > 0 && (
          <div className={styles.advice}>
            <b>§8.3 advisories</b>
            <ul>
              {advisories.map((a) => (
                <li key={a.key}>{a.text}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <footer className={styles.footer}>
        Traffic Ops<span className={styles.sep}>/</span>Phase 1 Sandbox
        <span className={styles.sep}>/</span>Webster 1958 · HCM 6th ed. · Handbook §8.3
      </footer>
    </main>
  );
}
