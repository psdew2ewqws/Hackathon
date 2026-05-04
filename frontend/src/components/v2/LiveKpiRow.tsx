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
  N: 'north',
  S: 'south',
  E: 'east',
  W: 'west',
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
        padding: '14px 16px',
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
            font: 'italic 400 18px var(--display)',
            color: 'var(--fg)',
            letterSpacing: '-0.01em',
          }}
        >
          Per-approach state
        </div>
        <div
          style={{
            font: '500 9px var(--mono)',
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--fg-faint)',
          }}
        >
          {error ? 'reconnecting' : 'fused · 1 hz'}
        </div>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gap: 10,
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
                padding: '12px 14px 14px',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: 3,
                  background: approachColor,
                }}
              />
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'baseline',
                  marginBottom: 10,
                }}
              >
                <div>
                  <span
                    style={{
                      font: '700 14px var(--mono)',
                      color: approachColor,
                      letterSpacing: '0.04em',
                    }}
                  >
                    {a}
                  </span>
                  <span
                    style={{
                      font: '500 9px var(--mono)',
                      letterSpacing: '0.16em',
                      textTransform: 'uppercase',
                      color: 'var(--fg-faint)',
                      marginLeft: 6,
                    }}
                  >
                    {APPROACH_FULL[a as Approach]}
                  </span>
                </div>
                <span
                  style={{
                    font: '600 9px var(--mono)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.16em',
                    color: tone,
                    padding: '2px 7px',
                    borderRadius: 999,
                    border: `1px solid ${tone}`,
                    background: 'transparent',
                  }}
                >
                  {row?.label ?? (error ? 'err' : '—')}
                </span>
              </div>

              <div
                style={{
                  font: 'italic 400 38px var(--display)',
                  color: 'var(--fg)',
                  letterSpacing: '-0.02em',
                  lineHeight: 1,
                  marginBottom: 2,
                }}
              >
                {fmt(row?.pressure, 2)}
              </div>
              <div
                style={{
                  font: '500 9px var(--mono)',
                  letterSpacing: '0.18em',
                  textTransform: 'uppercase',
                  color: 'var(--fg-faint)',
                  marginBottom: 12,
                }}
              >
                pressure index
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr 1fr',
                  gap: 10,
                  paddingTop: 10,
                  borderTop: '1px solid var(--border-soft)',
                }}
              >
                <Stat label="in zone" value={fmt(row?.in_zone)} />
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

function Stat({ label, value }: { label: string; value: string }) {
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
        {label}
      </div>
      <div
        style={{
          font: '600 15px var(--mono)',
          color: 'var(--fg)',
          letterSpacing: '-0.01em',
        }}
      >
        {value}
      </div>
    </div>
  );
}
