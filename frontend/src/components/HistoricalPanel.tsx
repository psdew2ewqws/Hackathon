import { useEffect, useMemo, useState, type ReactElement } from 'react';

interface HourlyPoint {
  hour: number;        // 0..23.75 in 0.25 steps (15-min bins)
  avg_count: number;
}

interface HistoryResponse {
  available: boolean;
  message?: string;
  days?: number;
  first_date?: string;
  last_date?: string;
  per_approach_hourly?: Record<'N' | 'S' | 'E' | 'W', HourlyPoint[]>;
  total_rows?: number;
}

const APPROACH_COLOR = {
  N: '#7FA889',
  S: '#E8B464',
  E: '#D68F6B',
  W: '#C084FC',
} as const;

export function HistoricalPanel() {
  const [data, setData] = useState<HistoryResponse | null>(null);

  useEffect(() => {
    let cancel = false;
    fetch('/api/history/counts?days=30')
      .then((r) => r.json())
      .then((j: HistoryResponse) => {
        if (!cancel) setData(j);
      })
      .catch(() => undefined);
    return () => {
      cancel = true;
    };
  }, []);

  const { svg, peaks } = useMemo(() => {
    const empty = { svg: null as ReactElement | null, peaks: {} as Record<string, { hour: number; avg: number }> };
    if (!data?.available || !data.per_approach_hourly) return empty;

    const W = 1100;
    const H = 220;
    const PAD_L = 36;
    const PAD_R = 12;
    const PAD_T = 12;
    const PAD_B = 24;
    const innerW = W - PAD_L - PAD_R;
    const innerH = H - PAD_T - PAD_B;

    // Find global max for y-scale
    let yMax = 0;
    for (const a of ['N', 'S', 'E', 'W'] as const) {
      const series = data.per_approach_hourly[a] ?? [];
      for (const p of series) yMax = Math.max(yMax, p.avg_count);
    }
    yMax = Math.max(1, yMax);

    const peakMap: Record<string, { hour: number; avg: number }> = {};
    const lines: ReactElement[] = [];
    for (const a of ['N', 'S', 'E', 'W'] as const) {
      const series = data.per_approach_hourly[a] ?? [];
      if (series.length === 0) continue;
      const points = series.map((p) => {
        const x = PAD_L + (p.hour / 24) * innerW;
        const y = PAD_T + innerH - (p.avg_count / yMax) * innerH;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      });
      lines.push(
        <polyline
          key={a}
          points={points.join(' ')}
          fill="none"
          stroke={APPROACH_COLOR[a]}
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeOpacity="0.85"
        />,
      );
      // Find peak hour
      let peak = series[0];
      for (const p of series) if (p.avg_count > peak.avg_count) peak = p;
      peakMap[a] = { hour: peak.hour, avg: peak.avg_count };
    }

    // Hour grid (every 4 hours)
    const grid: ReactElement[] = [];
    for (let h = 0; h <= 24; h += 4) {
      const x = PAD_L + (h / 24) * innerW;
      grid.push(
        <line
          key={`g${h}`}
          x1={x}
          x2={x}
          y1={PAD_T}
          y2={PAD_T + innerH}
          stroke="var(--border-soft)"
          strokeWidth="1"
          strokeDasharray="2 4"
        />,
      );
      grid.push(
        <text
          key={`t${h}`}
          x={x}
          y={H - 6}
          fill="var(--fg-faint)"
          fontSize="10"
          fontFamily="var(--mono)"
          textAnchor="middle"
        >
          {String(h).padStart(2, '0')}
        </text>,
      );
    }
    // Y axis labels (0, mid, max)
    for (const frac of [0, 0.5, 1]) {
      const y = PAD_T + innerH - frac * innerH;
      grid.push(
        <text
          key={`y${frac}`}
          x={PAD_L - 6}
          y={y + 3}
          fill="var(--fg-faint)"
          fontSize="10"
          fontFamily="var(--mono)"
          textAnchor="end"
        >
          {Math.round(yMax * frac)}
        </text>,
      );
    }

    return {
      svg: (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
          {grid}
          {lines}
        </svg>
      ),
      peaks: peakMap,
    };
  }, [data]);

  return (
    <section
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-md)',
        padding: '20px 22px',
        marginTop: 20,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 14,
        }}
      >
        <div>
          <h2
            style={{
              font: '500 13px var(--sans)',
              color: 'var(--fg)',
              margin: '0 0 6px',
            }}
          >
            Historical performance
          </h2>
          <p
            style={{
              font: '400 11px var(--mono)',
              color: 'var(--fg-faint)',
              margin: 0,
              lineHeight: 1.7,
            }}
          >
            {data?.available
              ? `Per-approach mean count per hour-of-day · ${data.days} days · ${data.first_date} → ${data.last_date} · ${data.total_rows?.toLocaleString()} rows`
              : 'Loading historical detector counts…'}
          </p>
        </div>
        <span
          style={{
            font: '500 11px var(--mono)',
            color: 'var(--fg-faint)',
            letterSpacing: '0.02em',
          }}
        >
          /api/history/counts
        </span>
      </div>

      <div
        style={{
          padding: 12,
          background: 'var(--surface-2)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--r-md)',
        }}
      >
        {svg ?? (
          <div
            style={{
              height: 220,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--fg-faint)',
              font: '400 11px var(--mono)',
            }}
          >
            {data?.message ?? 'no data'}
          </div>
        )}
      </div>

      {/* Per-approach legend + peaks */}
      <div
        style={{
          marginTop: 12,
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 10,
          font: '400 11px var(--mono)',
          color: 'var(--fg-dim)',
        }}
      >
        {(['N', 'S', 'E', 'W'] as const).map((a) => {
          const peak = peaks[a];
          return (
            <div
              key={a}
              style={{
                padding: '8px 12px',
                background: 'var(--surface-2)',
                border: '1px solid var(--border-soft)',
                borderRadius: 'var(--r-sm)',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  background: APPROACH_COLOR[a],
                  borderRadius: 2,
                  display: 'inline-block',
                }}
              />
              <span style={{ color: 'var(--fg)', fontWeight: 600 }}>{a}</span>
              {peak ? (
                <span>
                  peak {peak.hour.toFixed(1).padStart(4, '0')}h ·{' '}
                  <b style={{ color: 'var(--fg)' }}>{Math.round(peak.avg)}</b> avg
                </span>
              ) : (
                <span style={{ color: 'var(--fg-mute)' }}>no data</span>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
