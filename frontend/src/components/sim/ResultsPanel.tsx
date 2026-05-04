import { useEffect, useMemo, useState } from 'react';
import { getRecommendation } from '../../api/client';
import { APPROACHES, APPROACH_COLOR, type Approach } from '../../api/types';
import type { SimMetrics } from '../../lib/movsimBridge';

interface Props {
  latest: SimMetrics | null;
  history: SimMetrics[];
  ready: boolean;
}

export function ResultsPanel({ latest, history, ready }: Props) {
  const [websterDelay, setWebsterDelay] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    getRecommendation()
      .then((r) => {
        if (alive) {
          const cmp = r.recommendation?.comparison;
          setWebsterDelay(cmp?.recommended?.uniform_delay_sec_per_veh ?? null);
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Avg over last 30 frames (= 30 wall-seconds at 1 Hz emit)
  const rollingAvgDelay = useMemo(() => {
    if (history.length === 0) return null;
    const recent = history.slice(-30);
    return recent.reduce((s, m) => s + m.avg_delay_s_per_veh, 0) / recent.length;
  }, [history]);

  const deltaPct =
    rollingAvgDelay != null && websterDelay != null && websterDelay > 0
      ? ((rollingAvgDelay - websterDelay) / websterDelay) * 100
      : null;
  const deltaTone =
    deltaPct == null
      ? 'var(--fg-faint)'
      : deltaPct < -3
      ? 'var(--good)'
      : deltaPct > 3
      ? 'var(--bad)'
      : 'var(--fg-dim)';

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
        }}
      >
        <span
          style={{
            font: '600 11px var(--mono)',
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: 'var(--fg-bright)',
          }}
        >
          Simulated outcome
        </span>
        <span
          style={{
            font: '500 10px var(--mono)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: ready ? 'var(--good)' : 'var(--fg-faint)',
          }}
        >
          <span
            className={ready ? 'dot-pulse' : ''}
            style={{
              display: 'inline-block',
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: ready ? 'var(--good)' : 'var(--fg-faint)',
              marginRight: 6,
              boxShadow: ready ? '0 0 6px var(--good)' : 'none',
            }}
          />
          {ready ? 'sim live' : 'waiting for sim'} · {history.length} frames
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 10,
        }}
      >
        <Metric
          label="avg delay"
          unit="s/veh"
          value={latest ? latest.avg_delay_s_per_veh.toFixed(1) : '—'}
          tone="var(--fg-bright)"
        />
        <Metric
          label="throughput"
          unit="veh/15m"
          value={latest ? latest.throughput_per_15min.toFixed(0) : '—'}
          tone="var(--fg-bright)"
        />
        <Metric
          label="active veh"
          unit="now"
          value={latest ? String(latest.vehicles_active) : '—'}
          tone="var(--fg-bright)"
        />
        <Metric
          label="vs Webster"
          unit="delay Δ"
          value={
            deltaPct == null
              ? '—'
              : `${deltaPct >= 0 ? '+' : '−'}${Math.abs(deltaPct).toFixed(0)}%`
          }
          tone={deltaTone}
        />
      </div>

      {latest && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 8,
            paddingTop: 12,
            borderTop: '1px solid var(--border-soft)',
          }}
        >
          {APPROACHES.map((a) => {
            const q = latest.queue_length[a as Approach] ?? 0;
            return (
              <div
                key={a}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 3,
                  padding: '6px 10px',
                  borderLeft: `2px solid ${APPROACH_COLOR[a as Approach]}`,
                }}
              >
                <span
                  style={{
                    font: '600 9px var(--mono)',
                    letterSpacing: '0.18em',
                    textTransform: 'uppercase',
                    color: 'var(--fg-faint)',
                  }}
                >
                  {a} queue
                </span>
                <span
                  className="tabular"
                  style={{
                    font: '700 18px var(--sans)',
                    color: 'var(--fg-bright)',
                    letterSpacing: '-0.02em',
                  }}
                >
                  {q.toFixed(0)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* tiny rolling sparkline of avg_delay */}
      {history.length > 4 && <DelaySpark history={history} />}
    </div>
  );
}

function Metric({
  label,
  unit,
  value,
  tone,
}: {
  label: string;
  unit: string;
  value: string;
  tone: string;
}) {
  return (
    <div>
      <div
        style={{
          font: '500 9px var(--mono)',
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
          marginBottom: 2,
        }}
      >
        {label} · {unit}
      </div>
      <div
        className="tabular"
        style={{
          font: '700 24px var(--sans)',
          color: tone,
          letterSpacing: '-0.02em',
          lineHeight: 1,
        }}
      >
        {value}
      </div>
    </div>
  );
}

function DelaySpark({ history }: { history: SimMetrics[] }) {
  const W = 600;
  const H = 40;
  const values = history.map((m) => m.avg_delay_s_per_veh);
  const max = Math.max(1, ...values);
  const xs = values.map((_, i) => (i / Math.max(1, values.length - 1)) * W);
  const ys = values.map((v) => H - (v / max) * H);
  const path = xs
    .map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${ys[i].toFixed(1)}`)
    .join(' ');
  const area = `${path} L${W},${H} L0,${H} Z`;
  return (
    <div>
      <div
        style={{
          font: '500 9px var(--mono)',
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
          marginBottom: 4,
        }}
      >
        delay history · last {history.length} frames
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: H, display: 'block' }}
      >
        <path d={area} fill="var(--ai)" fillOpacity={0.12} />
        <path d={path} fill="none" stroke="var(--ai)" strokeWidth={1.5} />
      </svg>
    </div>
  );
}
