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

const APPROACH_FULL: Record<Approach, string> = {
  N: 'NORTH',
  S: 'SOUTH',
  E: 'EAST',
  W: 'WEST',
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
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '10px 12px 12px',
      }}
    >
      <PanelHeader title="Per-approach state" meta={error ? 'reconnecting…' : 'fused · 1 Hz'} />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gap: 8,
        }}
      >
        {APPROACHES.map((a) => {
          const row = data?.fused?.[a as Approach];
          const tone = row?.label
            ? LABEL_TONE[row.label] ?? 'var(--fg-dim)'
            : 'var(--fg-faint)';
          const approachColor = APPROACH_COLOR[a as Approach];
          return (
            <div
              key={a}
              style={{
                position: 'relative',
                background: 'var(--surface)',
                border: '1px solid var(--border-soft)',
                borderRadius: 'var(--r-md)',
                padding: '10px 12px 11px',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: 2,
                  background: approachColor,
                }}
              />
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 6,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                  <span
                    style={{
                      font: '700 13px var(--mono)',
                      color: approachColor,
                      letterSpacing: '0.04em',
                    }}
                  >
                    {a}
                  </span>
                  <span
                    style={{
                      font: '500 9px var(--mono)',
                      letterSpacing: '0.18em',
                      color: 'var(--fg-faint)',
                    }}
                  >
                    {APPROACH_FULL[a as Approach]}
                  </span>
                </div>
                <span
                  style={{
                    font: '600 9px var(--mono)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.18em',
                    color: tone,
                    padding: '2px 6px',
                    borderRadius: 4,
                    border: `1px solid ${tone}`,
                  }}
                >
                  {row?.label ?? (error ? 'err' : '—')}
                </span>
              </div>

              <div
                className="tabular"
                style={{
                  font: '700 30px var(--sans)',
                  color: 'var(--fg-bright)',
                  letterSpacing: '-0.025em',
                  lineHeight: 1,
                  marginBottom: 2,
                }}
              >
                {fmt(row?.pressure, 2)}
              </div>
              <div
                style={{
                  font: '500 9px var(--mono)',
                  letterSpacing: '0.16em',
                  textTransform: 'uppercase',
                  color: 'var(--fg-faint)',
                  marginBottom: 9,
                }}
              >
                pressure index
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr 1fr',
                  gap: 8,
                  paddingTop: 9,
                  borderTop: '1px solid var(--border-soft)',
                }}
              >
                <Stat label="zone" value={fmt(row?.in_zone)} />
                <Stat label="queue" value={fmt(row?.queue)} />
                <Stat label="gmaps" value={fmt(row?.gmaps_congestion_ratio, 2)} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PanelHeader({ title, meta }: { title: string; meta: string }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        marginBottom: 10,
      }}
    >
      <div
        style={{
          font: '600 11px var(--mono)',
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          color: 'var(--fg-bright)',
        }}
      >
        {title}
      </div>
      <div
        style={{
          font: '500 10px var(--mono)',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
        }}
      >
        {meta}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        style={{
          font: '500 8.5px var(--mono)',
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
          marginBottom: 1,
        }}
      >
        {label}
      </div>
      <div
        className="tabular"
        style={{
          font: '600 14px var(--mono)',
          color: 'var(--fg)',
          letterSpacing: '-0.01em',
        }}
      >
        {value}
      </div>
    </div>
  );
}
