import { useEffect, useState } from 'react';
import { getFusion } from '../../api/client';
import {
  APPROACHES,
  APPROACH_COLOR,
  type Approach,
  type FusionResponse,
} from '../../api/types';

const LABEL_TONE: Record<string, string> = {
  free: 'var(--good)',
  light: 'var(--accent)',
  moderate: 'var(--accent)',
  heavy: 'var(--warn)',
  jam: 'var(--bad)',
};

function fmt(n: number | undefined | null, digits = 0): string {
  if (n === undefined || n === null || Number.isNaN(n)) return '—';
  return n.toFixed(digits);
}

export function LiveKpiRow() {
  const [data, setData] = useState<FusionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let t: number;
    const tick = async () => {
      try {
        const f = await getFusion();
        if (!alive) return;
        setData(f);
        setError(null);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
      if (alive) t = window.setTimeout(tick, 1000);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
        gap: 12,
        marginBottom: 14,
      }}
    >
      {APPROACHES.map((a) => {
        const row = data?.fused?.[a as Approach];
        const tone = row?.label ? LABEL_TONE[row.label] ?? 'var(--fg-dim)' : 'var(--fg-faint)';
        return (
          <div
            key={a}
            style={{
              background: 'var(--surface)',
              border: '1px solid var(--border-soft)',
              borderRadius: 'var(--r-md)',
              padding: '12px 14px',
              borderLeft: `3px solid ${APPROACH_COLOR[a as Approach]}`,
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                marginBottom: 8,
              }}
            >
              <span
                style={{
                  font: '700 14px var(--mono)',
                  color: APPROACH_COLOR[a as Approach],
                  letterSpacing: '0.04em',
                }}
              >
                {a}
              </span>
              <span
                style={{
                  font: '500 10px var(--mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  color: tone,
                }}
              >
                {row?.label ?? (error ? 'err' : '—')}
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              <Stat label="in zone" value={fmt(row?.in_zone)} />
              <Stat label="queue" value={fmt(row?.queue)} />
              <Stat label="pressure" value={fmt(row?.pressure, 2)} />
              <Stat label="gmaps ratio" value={fmt(row?.gmaps_congestion_ratio, 2)} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        style={{
          font: '500 9px var(--mono)',
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
        }}
      >
        {label}
      </div>
      <div style={{ font: '600 16px var(--mono)', color: 'var(--fg)' }}>{value}</div>
    </div>
  );
}
