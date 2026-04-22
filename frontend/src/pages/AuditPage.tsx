import { useEffect, useMemo, useState } from 'react';
import styles from './InfoPage.module.css';

interface AuditRecord {
  ts: string;
  ip: string;
  method: string;
  path: string;
  code: number;
}

interface AuditResponse {
  available: boolean;
  message?: string;
  count?: number;
  records?: AuditRecord[];
}

function statusClass(code: number): string {
  if (code >= 500) return styles.statusCode5xx;
  if (code >= 400) return styles.statusCode4xx;
  if (code >= 300) return styles.statusCode3xx;
  if (code >= 200) return styles.statusCode200;
  return '';
}

export function AuditPage() {
  const [data, setData] = useState<AuditResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [limit, setLimit] = useState(200);
  const [pathFilter, setPathFilter] = useState('');
  const [codeFilter, setCodeFilter] = useState('all');

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const res = await fetch(`/api/audit?n=${limit}`);
        if (!res.ok) throw new Error(`audit ${res.status}`);
        const j = (await res.json()) as AuditResponse;
        if (!cancelled) {
          setData(j);
          setErr(null);
        }
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      }
    };
    fetchOnce();
    const id = window.setInterval(fetchOnce, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [limit]);

  const records = data?.records ?? [];
  const filtered = useMemo(() => {
    let r = records;
    if (pathFilter.trim()) {
      const q = pathFilter.toLowerCase();
      r = r.filter((x) => x.path.toLowerCase().includes(q));
    }
    if (codeFilter !== 'all') {
      const bucket = codeFilter;
      r = r.filter((x) => {
        if (bucket === '2xx') return x.code >= 200 && x.code < 300;
        if (bucket === '3xx') return x.code >= 300 && x.code < 400;
        if (bucket === '4xx') return x.code >= 400 && x.code < 500;
        if (bucket === '5xx') return x.code >= 500;
        return true;
      });
    }
    // newest first
    return [...r].reverse();
  }, [records, pathFilter, codeFilter]);

  // Bucket counts over the currently-loaded window
  const bucketCounts = useMemo(() => {
    const b = { '2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0 };
    for (const r of records) {
      if (r.code >= 200 && r.code < 300) b['2xx']++;
      else if (r.code >= 300 && r.code < 400) b['3xx']++;
      else if (r.code >= 400 && r.code < 500) b['4xx']++;
      else if (r.code >= 500) b['5xx']++;
    }
    return b;
  }, [records]);

  return (
    <main className={styles.page}>
      <header className={styles.head}>
        <div>
          <h1 className={styles.title}>Audit Log</h1>
          <div className={styles.subtitle}>
            §7.7 — every request that reaches the viewer HTTP server.
            Read-only, rotated at 50 MB.
          </div>
        </div>
        <div className={styles.headRight}>
          showing {filtered.length} / {records.length}
        </div>
      </header>

      {err && (
        <div className={styles.panel} style={{ borderColor: 'rgba(214,143,107,0.4)' }}>
          <span style={{ color: 'var(--warn)' }}>Audit endpoint error: {err}</span>
        </div>
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
              <div className={styles.label}>2xx</div>
              <div className={styles.value} style={{ color: 'var(--good)' }}>
                {bucketCounts['2xx']}
              </div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.label}>3xx</div>
              <div className={styles.value} style={{ color: 'var(--accent)' }}>
                {bucketCounts['3xx']}
              </div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.label}>4xx</div>
              <div className={styles.value} style={{ color: 'var(--warn)' }}>
                {bucketCounts['4xx']}
              </div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.label}>5xx</div>
              <div className={styles.value} style={{ color: 'var(--warn)' }}>
                {bucketCounts['5xx']}
              </div>
            </div>
          </div>

          <div className={styles.toolbar}>
            window:
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              <option value={50}>last 50</option>
              <option value={200}>last 200</option>
              <option value={500}>last 500</option>
              <option value={1000}>last 1000</option>
            </select>
            status:
            <select value={codeFilter} onChange={(e) => setCodeFilter(e.target.value)}>
              <option value="all">all</option>
              <option value="2xx">2xx</option>
              <option value="3xx">3xx</option>
              <option value="4xx">4xx</option>
              <option value="5xx">5xx</option>
            </select>
            path contains:
            <input
              type="text"
              value={pathFilter}
              placeholder="/api/"
              onChange={(e) => setPathFilter(e.target.value)}
              style={{ minWidth: 180 }}
            />
          </div>

          <div className={styles.panel} style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ maxHeight: 620, overflowY: 'auto' }}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th style={{ width: 180 }}>Timestamp</th>
                    <th style={{ width: 110 }}>IP</th>
                    <th style={{ width: 70 }}>Method</th>
                    <th style={{ width: 70 }}>Code</th>
                    <th>Path</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r, i) => (
                    <tr key={`${r.ts}-${i}`}>
                      <td className="mono" style={{ fontFamily: 'var(--mono)', color: 'var(--fg-faint)' }}>
                        {r.ts.slice(11, 23)}
                      </td>
                      <td className="mono" style={{ fontFamily: 'var(--mono)' }}>
                        {r.ip}
                      </td>
                      <td className="mono" style={{ fontFamily: 'var(--mono)' }}>
                        {r.method}
                      </td>
                      <td className={`mono ${statusClass(r.code)}`} style={{ fontFamily: 'var(--mono)' }}>
                        <b>{r.code || '—'}</b>
                      </td>
                      <td className="mono" style={{ fontFamily: 'var(--mono)' }}>
                        {r.path}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
