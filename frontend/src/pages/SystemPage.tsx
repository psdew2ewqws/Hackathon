import { useEffect, useState } from 'react';
import styles from './SystemPage.module.css';

type Status = 'up' | 'idle' | 'down';

interface Module {
  id: string;
  layer: 'Source' | 'Ingest+AI' | 'Analytics' | 'Dashboard';
  display: string;
  path: string;
  status: Status;
  pid?: number;
  uptime_s?: number;
  cpu_pct?: number;
  rss_mb?: number;
  fps?: number;
  detections_last_bin?: number;
  detail?: string;
}

interface StorageRow {
  name: string;
  path: string;
  format: string;
  section: string;
  exists: boolean;
  size_bytes: number;
  mtime_age_s: number | null;
}

interface Flow {
  id: string;
  name: string;
  from: string;
  to: string;
  throughput: string;
  healthy: boolean;
}

interface Fault {
  name: string;
  mitigation: string;
  active: boolean;
}

interface LogRow {
  path: string;
  exists: boolean;
  size_bytes: number;
  mtime_age_s: number | null;
}

interface Monitoring {
  endpoints: string[];
  logs: LogRow[];
  freshness: Record<string, number | null>;
}

interface ReadinessRow {
  dimension: string;
  ready: boolean;
  note: string;
}

interface MultiSite {
  current_sites: string[];
  readiness: ReadinessRow[];
}

interface Architecture {
  generated_at: string;
  site_id: string;
  modules: Module[];
  storage: StorageRow[];
  flows: Flow[];
  faults: Fault[];
  monitoring: Monitoring;
  multi_site: MultiSite;
}

const LAYER_ORDER: Module['layer'][] = [
  'Source',
  'Ingest+AI',
  'Analytics',
  'Dashboard',
];

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function fmtDuration(s: number | null | undefined): string {
  if (s == null) return '—';
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function statusPillClass(s: Status): string {
  return s === 'up'
    ? styles.pillUp
    : s === 'down'
      ? styles.pillDown
      : styles.pillIdle;
}

function statusDotClass(s: Status): string {
  return s === 'up'
    ? styles.statusDotUp
    : s === 'down'
      ? styles.statusDotDown
      : styles.statusDotIdle;
}

function moduleClass(s: Status): string {
  return s === 'up'
    ? styles.moduleUp
    : s === 'down'
      ? styles.moduleDown
      : styles.moduleIdle;
}

export function SystemPage() {
  const [data, setData] = useState<Architecture | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const res = await fetch('/api/architecture');
        if (!res.ok) throw new Error(`architecture ${res.status}`);
        const j = (await res.json()) as Architecture;
        if (!cancelled) {
          setData(j);
          setErr(null);
        }
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      }
    };
    fetchOnce();
    const id = window.setInterval(fetchOnce, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const byLayer = (layer: Module['layer']) =>
    (data?.modules ?? []).filter((m) => m.layer === layer);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <div>
          <h1 className={styles.brandTitle} style={{ margin: 0 }}>
            Architecture
          </h1>
          <div style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)',
                        marginTop: 2, letterSpacing: '0.04em' }}>
            §7.1 deliverable · live module + storage + fault snapshot
          </div>
        </div>
        <div />
        <span className={styles.panelHint}>refreshed every 3s</span>
      </header>

      {err && (
        <div className={styles.panel} style={{ borderColor: 'rgba(214,143,107,0.4)' }}>
          <span style={{ color: 'var(--warn)' }}>Architecture endpoint error: {err}</span>
        </div>
      )}

      {!data && !err && (
        <div className={styles.panel}>
          <span style={{ color: 'var(--fg-dim)' }}>Loading system snapshot…</span>
        </div>
      )}

      {data && (
        <>
          {/* ── 1. MODULES × LAYERS (block diagram) ───────────────── */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <div>
                <h2 className={styles.panelTitle}>
                  Modules by layer ({data.modules.length})
                </h2>
                <p style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)',
                            marginTop: 4 }}>
                  Live process + file status. Green = running, gray = idle, amber = down.
                </p>
              </div>
              <span className={styles.panelHint}>/api/architecture</span>
            </div>

            <div className={styles.layerGrid}>
              {LAYER_ORDER.map((layer) => (
                <div key={layer} className={styles.layer}>
                  <div className={styles.layerHead}>{layer} layer</div>
                  <div className={styles.moduleRow}>
                    {byLayer(layer).map((m) => (
                      <div key={m.id} className={`${styles.module} ${moduleClass(m.status)}`}>
                        <div className={styles.moduleName}>
                          <span className={`${styles.statusDot} ${statusDotClass(m.status)}`} />
                          {m.display}
                          <span style={{ flex: 1 }} />
                          <span className={`${styles.pill} ${statusPillClass(m.status)}`}>
                            {m.status}
                          </span>
                        </div>
                        <div className={styles.modulePath} title={m.path}>{m.path}</div>
                        <div className={styles.moduleStats}>
                          {m.pid != null && <span className={styles.moduleStat}>pid <b>{m.pid}</b></span>}
                          {m.uptime_s != null && <span className={styles.moduleStat}>up <b>{fmtDuration(m.uptime_s)}</b></span>}
                          {m.cpu_pct != null && <span className={styles.moduleStat}>cpu <b>{m.cpu_pct.toFixed(0)}%</b></span>}
                          {m.rss_mb != null && <span className={styles.moduleStat}>rss <b>{m.rss_mb.toFixed(0)} MB</b></span>}
                          {m.fps != null && <span className={styles.moduleStat}>fps <b>{m.fps.toFixed(1)}</b></span>}
                          {m.detections_last_bin != null && <span className={styles.moduleStat}>det <b>{m.detections_last_bin}</b></span>}
                        </div>
                        {m.detail && (
                          <div style={{ font: '400 10px var(--mono)',
                                        color: 'var(--fg-faint)', marginTop: 6 }}>
                            {m.detail}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* ── 2. DATA FLOWS ──────────────────────────────────── */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>
                Data flows ({data.flows.length})
              </h2>
              <span className={styles.panelHint}>§7.1 F1 / F2 / F3</span>
            </div>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name</th>
                  <th>From → To</th>
                  <th>Throughput</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.flows.map((f) => (
                  <tr key={f.id}>
                    <td className={styles.mono}><b>{f.id}</b></td>
                    <td>{f.name}</td>
                    <td className={styles.mono}>
                      {f.from}
                      <span className={styles.flowArrow}>→</span>
                      {f.to}
                    </td>
                    <td className={styles.mono}>{f.throughput}</td>
                    <td>
                      <span className={`${styles.pill} ${f.healthy ? styles.pillUp : styles.pillDown}`}>
                        {f.healthy ? 'live' : 'stale'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* ── 3. STORAGE + LOGGING ───────────────────────────── */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>
                Storage + logging ({data.storage.length})
              </h2>
              <span className={styles.panelHint}>live sizes, mtime-age</span>
            </div>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Artifact</th>
                  <th>Path</th>
                  <th>Format</th>
                  <th>§</th>
                  <th style={{ textAlign: 'right' }}>Size</th>
                  <th style={{ textAlign: 'right' }}>Age</th>
                </tr>
              </thead>
              <tbody>
                {data.storage.map((s) => (
                  <tr key={s.path}>
                    <td><b>{s.name}</b></td>
                    <td className={styles.mono} style={{ color: 'var(--fg-faint)' }}>{s.path}</td>
                    <td className={styles.mono}>{s.format}</td>
                    <td className={styles.mono}>{s.section}</td>
                    <td className={styles.mono} style={{ textAlign: 'right' }}>
                      {s.exists ? fmtBytes(s.size_bytes) : <span style={{ color: 'var(--warn)' }}>missing</span>}
                    </td>
                    <td className={styles.mono} style={{ textAlign: 'right' }}>
                      {fmtDuration(s.mtime_age_s)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* ── 4. FAULT-HANDLING PATHS ──────────────────────── */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>
                Fault-handling paths ({data.faults.length})
              </h2>
              <span className={styles.panelHint}>
                {data.faults.filter((f) => f.active).length} active
              </span>
            </div>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Failure</th>
                  <th>Mitigation</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {data.faults.map((f) => (
                  <tr key={f.name}>
                    <td><b>{f.name}</b></td>
                    <td>{f.mitigation}</td>
                    <td>
                      <span className={`${styles.pill} ${f.active ? styles.pillActive : styles.pillIdle}`}>
                        {f.active ? 'firing' : 'nominal'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* ── 5. MONITORING PATHS ──────────────────────────── */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>System monitoring</h2>
              <span className={styles.panelHint}>
                phase2 events {fmtDuration(data.monitoring.freshness.phase2_events_ndjson_age_s)} old
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
              <div>
                <div style={{ font: '600 10px var(--mono)', letterSpacing: '0.06em',
                              textTransform: 'uppercase', color: 'var(--fg-faint)',
                              marginBottom: 8 }}>
                  Health endpoints
                </div>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0,
                             font: '400 12px var(--mono)' }}>
                  {data.monitoring.endpoints.map((e) => (
                    <li key={e} style={{ padding: '4px 0', color: 'var(--fg-dim)' }}>
                      <span style={{ color: 'var(--good)' }}>● </span>
                      {e}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <div style={{ font: '600 10px var(--mono)', letterSpacing: '0.06em',
                              textTransform: 'uppercase', color: 'var(--fg-faint)',
                              marginBottom: 8 }}>
                  Process logs
                </div>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Path</th>
                      <th style={{ textAlign: 'right' }}>Size</th>
                      <th style={{ textAlign: 'right' }}>Age</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.monitoring.logs.map((l) => (
                      <tr key={l.path}>
                        <td className={styles.mono} style={{ fontSize: 10 }}>{l.path}</td>
                        <td className={styles.mono} style={{ textAlign: 'right' }}>
                          {l.exists ? fmtBytes(l.size_bytes) : '—'}
                        </td>
                        <td className={styles.mono} style={{ textAlign: 'right' }}>
                          {fmtDuration(l.mtime_age_s)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          {/* ── 6. MULTI-SITE READINESS ─────────────────────── */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <div>
                <h2 className={styles.panelTitle}>
                  Multi-site scale readiness
                </h2>
                <p style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)',
                            marginTop: 4 }}>
                  Current sites: <b style={{ color: 'var(--fg)' }}>
                    {data.multi_site.current_sites.join(', ')}
                  </b>
                </p>
              </div>
              <span className={styles.panelHint}>
                {data.multi_site.readiness.filter((r) => r.ready).length} /
                {' '}{data.multi_site.readiness.length} ready
              </span>
            </div>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Dimension</th>
                  <th>Note</th>
                  <th>Ready?</th>
                </tr>
              </thead>
              <tbody>
                {data.multi_site.readiness.map((r) => (
                  <tr key={r.dimension}>
                    <td><b>{r.dimension}</b></td>
                    <td className={styles.mono} style={{ color: 'var(--fg-dim)' }}>{r.note}</td>
                    <td>
                      <span className={`${styles.pill} ${r.ready ? styles.pillUp : styles.pillIdle}`}>
                        {r.ready ? 'ready' : 'todo'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <footer className={styles.footer}>
            Generated {data.generated_at} · site {data.site_id} · polled every 3 s
          </footer>
        </>
      )}
    </main>
  );
}
