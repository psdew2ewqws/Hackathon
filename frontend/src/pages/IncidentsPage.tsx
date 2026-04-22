import { useEffect, useMemo, useState } from 'react';
import styles from './InfoPage.module.css';

interface IncidentRow {
  clip: string;
  tag: string;
  confidence: number | null;
  classifier: string | null;
  pass: string | null;
  reasons: string[];
  interpretation: string;
  line_crossings: Record<string, number>;
  detections: number | null;
  tracks: number | null;
  frames: number | null;
  artifacts: {
    raw?: string;
    normalized?: string;
    annotated?: string;
    events?: string;
  };
}

interface IncidentsResponse {
  available: boolean;
  message?: string;
  schema?: string;
  intersection_id?: string;
  total?: number;
  tag_counts?: Record<string, number>;
  rows?: IncidentRow[];
}

const INCIDENT_TAGS = new Set(['queue_spillback', 'stalled_vehicle',
  'sudden_congestion', 'abnormal_stop', 'unexpected_trajectory',
  'incident', 'accident']);

function tagClass(tag: string): { card: string; pill: string } {
  if (tag === 'normal') return { card: styles.cardNormal, pill: styles.tagNormal };
  if (INCIDENT_TAGS.has(tag)) {
    return { card: styles.cardIncident, pill: styles.tagIncident };
  }
  return { card: styles.cardWarn, pill: styles.tagWarn };
}

export function IncidentsPage() {
  const [data, setData] = useState<IncidentsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>('all');

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const res = await fetch('/api/incidents');
        if (!res.ok) throw new Error(`incidents ${res.status}`);
        const j = (await res.json()) as IncidentsResponse;
        if (!cancelled) {
          setData(j);
          setErr(null);
        }
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      }
    };
    fetchOnce();
    const id = window.setInterval(fetchOnce, 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const visibleRows = useMemo(() => {
    const rows = data?.rows ?? [];
    if (filter === 'all') return rows;
    if (filter === 'incidents') return rows.filter((r) => r.tag !== 'normal');
    return rows.filter((r) => r.tag === filter);
  }, [data, filter]);

  const counts = data?.tag_counts ?? {};
  const total = data?.total ?? 0;
  const incidentTotal = Object.entries(counts)
    .filter(([k]) => k !== 'normal')
    .reduce((a, [, v]) => a + v, 0);

  return (
    <main className={styles.page}>
      <header className={styles.head}>
        <div>
          <h1 className={styles.title}>Incidents</h1>
          <div className={styles.subtitle}>
            Classifier verdicts from `data/labels/clips_manifest.json` ·
            {' '}{data?.schema ?? '…'} · site {data?.intersection_id ?? '…'}
          </div>
        </div>
        <div className={styles.headRight}>
          {data?.available ? `${visibleRows.length}/${total} clips` : '—'}
        </div>
      </header>

      {err && (
        <div className={styles.panel} style={{ borderColor: 'rgba(214,143,107,0.4)' }}>
          <span style={{ color: 'var(--warn)' }}>Incidents endpoint error: {err}</span>
        </div>
      )}

      {!data && !err && (
        <div className={styles.empty}>Loading incidents…</div>
      )}

      {data && !data.available && (
        <div className={styles.panel}>
          <span style={{ color: 'var(--fg-dim)' }}>{data.message}</span>
        </div>
      )}

      {data?.available && (
        <>
          <div className={styles.summary}>
            <div className={styles.summaryCard}>
              <div className={styles.label}>Total clips</div>
              <div className={styles.value}>{total}</div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.label}>Incidents flagged</div>
              <div className={styles.value} style={{ color: incidentTotal > 0 ? 'var(--warn)' : 'var(--good)' }}>
                {incidentTotal}
              </div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.label}>Normal</div>
              <div className={styles.value} style={{ color: 'var(--good)' }}>
                {counts['normal'] ?? 0}
              </div>
            </div>
          </div>

          <div className={styles.toolbar}>
            filter:
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="all">all tags</option>
              <option value="incidents">incidents only</option>
              <option value="normal">normal only</option>
              {Object.keys(counts)
                .filter((t) => t !== 'normal')
                .map((t) => (
                  <option key={t} value={t}>
                    {t} ({counts[t]})
                  </option>
                ))}
            </select>
          </div>

          {visibleRows.length === 0 && (
            <div className={styles.empty}>No clips match the current filter.</div>
          )}

          {visibleRows.map((r) => {
            const cls = tagClass(r.tag);
            const lc = r.line_crossings || {};
            return (
              <div key={r.clip} className={`${styles.card} ${cls.card}`}>
                <div className={styles.cardHead}>
                  <h2 className={styles.cardTitle}>{r.clip}</h2>
                  <span className={`${styles.tag} ${cls.pill}`}>{r.tag}</span>
                  <span className={styles.conf}>
                    {r.confidence != null ? `conf ${r.confidence.toFixed(2)}` : '—'} ·
                    {' '}{r.classifier ?? 'unknown'} · pass {r.pass ?? '?'}
                  </span>
                </div>
                {r.interpretation && (
                  <div className={styles.interp}>{r.interpretation}</div>
                )}
                <div className={styles.meta}>
                  <span>frames <b>{r.frames ?? '—'}</b></span>
                  <span>detections <b>{r.detections ?? '—'}</b></span>
                  <span>tracks <b>{r.tracks ?? '—'}</b></span>
                  <span>
                    crossings N=<b>{lc.N ?? 0}</b> S=<b>{lc.S ?? 0}</b>{' '}
                    E=<b>{lc.E ?? 0}</b> W=<b>{lc.W ?? 0}</b>
                  </span>
                </div>
                {r.reasons.length > 0 && (
                  <div className={styles.reasons}>
                    <ul>
                      {r.reasons.map((rz, i) => (
                        <li key={i}>{rz}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </main>
  );
}
