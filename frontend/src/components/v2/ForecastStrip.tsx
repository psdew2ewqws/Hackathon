import { useEffect, useMemo, useState } from 'react';
import { getForecastMl } from '../../api/client';
import {
  APPROACHES,
  APPROACH_COLOR,
  type Approach,
  type ForecastMlResponse,
} from '../../api/types';

const HORIZONS: Array<{ key: 'y_now' | 'y_15min' | 'y_30min' | 'y_60min'; label: string }> = [
  { key: 'y_now', label: 'now' },
  { key: 'y_15min', label: '+15' },
  { key: 'y_30min', label: '+30' },
  { key: 'y_60min', label: '+60' },
];

interface PerApproachAgg {
  approach: Approach;
  values: number[]; // [now, +15, +30, +60]
  delta60Pct: number | null;
}

function aggregate(data: ForecastMlResponse | null): PerApproachAgg[] {
  if (!data?.per_detector) {
    return APPROACHES.map((a) => ({
      approach: a as Approach,
      values: [0, 0, 0, 0],
      delta60Pct: null,
    }));
  }
  const sums: Record<Approach, number[]> = {
    S: [0, 0, 0, 0],
    N: [0, 0, 0, 0],
    E: [0, 0, 0, 0],
    W: [0, 0, 0, 0],
  };
  for (const det of Object.values(data.per_detector)) {
    const a = det.approach as Approach;
    if (!sums[a]) continue;
    sums[a][0] += det.y_now;
    sums[a][1] += det.y_15min;
    sums[a][2] += det.y_30min;
    sums[a][3] += det.y_60min;
  }
  return APPROACHES.map((a) => {
    const v = sums[a as Approach];
    const delta = v[0] > 0 ? ((v[3] - v[0]) / v[0]) * 100 : null;
    return { approach: a as Approach, values: v, delta60Pct: delta };
  });
}

export function ForecastStrip() {
  const [data, setData] = useState<ForecastMlResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getForecastMl();
        if (alive) {
          setData(r);
          setError(null);
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    tick();
    const id = window.setInterval(tick, 60_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const aggs = useMemo(() => aggregate(data), [data]);
  const globalMax = useMemo(
    () => Math.max(1, ...aggs.flatMap((a) => a.values)),
    [aggs],
  );

  const available = data?.available !== false;

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '14px 16px',
        marginBottom: 14,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 12,
        }}
      >
        <div
          style={{
            font: '600 11px var(--mono)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--fg-dim)',
          }}
        >
          Forecast strip · LightGBM horizons
        </div>
        <div
          style={{
            font: '400 10px var(--mono)',
            color: 'var(--fg-faint)',
          }}
        >
          {data?.target_ts ? new Date(data.target_ts).toLocaleTimeString() : 'loading…'}
        </div>
      </div>

      {error && (
        <div style={{ font: '500 11px var(--mono)', color: 'var(--bad)', marginBottom: 8 }}>
          {error}
        </div>
      )}
      {!available && data?.message && (
        <div style={{ font: '500 11px var(--mono)', color: 'var(--fg-faint)', marginBottom: 8 }}>
          {data.message}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {aggs.map((a) => (
          <Row key={a.approach} agg={a} max={globalMax} />
        ))}
      </div>

      <div
        style={{
          marginTop: 12,
          display: 'flex',
          gap: 16,
          font: '400 10px var(--mono)',
          color: 'var(--fg-faint)',
        }}
      >
        {HORIZONS.map((h) => (
          <span key={h.key}>{h.label}</span>
        ))}
      </div>
    </div>
  );
}

function Row({ agg, max }: { agg: PerApproachAgg; max: number }) {
  const color = APPROACH_COLOR[agg.approach];
  const W = 320;
  const H = 28;
  const xs = agg.values.map((_, i) => (i / (agg.values.length - 1)) * W);
  const ys = agg.values.map((v) => H - (v / max) * H);
  const path = xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ');
  const d = agg.delta60Pct;
  const arrow = d == null ? '' : d > 5 ? '↑' : d < -5 ? '↓' : '→';
  const tone = d == null ? 'var(--fg-faint)' : d > 5 ? 'var(--warn)' : d < -5 ? 'var(--good)' : 'var(--fg-dim)';

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '28px 1fr 110px',
        gap: 10,
        alignItems: 'center',
      }}
    >
      <div style={{ font: '700 12px var(--mono)', color }}>{agg.approach}</div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H }}>
        <path d={path} fill="none" stroke={color} strokeWidth={1.5} />
        {xs.map((x, i) => (
          <circle key={i} cx={x} cy={ys[i]} r={2} fill={color} />
        ))}
      </svg>
      <div style={{ font: '500 11px var(--mono)', color: tone, textAlign: 'right' }}>
        {d == null ? '—' : `${arrow} ${Math.abs(d).toFixed(0)}% @ +60`}
      </div>
    </div>
  );
}
