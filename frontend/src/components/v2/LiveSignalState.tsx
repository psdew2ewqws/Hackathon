import { useEffect, useRef, useState } from 'react';
import { apiUrl } from '../../api/client';

interface SignalCurrent {
  timestamp: string;
  cycle_number: number;
  phase_number: number;
  phase_name: string; // 'NS' | 'E' | 'W' | 'EW'
  signal_state: string; // 'GREEN ON' | 'YELLOW ON' | 'RED ON'
  approaches_affected: string[];
  duration_seconds: number;
  source: string;
  video_ts_seconds?: number;
}

interface SignalSnapshot {
  running: boolean;
  intersection_id: string;
  plan: {
    NS_green: number;
    EW_green: number;
    E_green?: number;
    W_green?: number;
    yellow: number;
    all_red: number;
    cycle_seconds: number;
    mode: string;
  };
  current: SignalCurrent | null;
}

const PHASE_COLOR = {
  NS: '#6FA8D6',
  E: '#7FA889',
  W: '#C583C5',
  EW: '#E8B464',
} as const;

const STATE_DOT = {
  'GREEN ON': '#7FA889',
  'YELLOW ON': '#E8B464',
  'RED ON': '#E46F6F',
} as const;

export function LiveSignalState() {
  const [snap, setSnap] = useState<SignalSnapshot | null>(null);
  const phaseStartRef = useRef<number | null>(null);
  const lastTsRef = useRef<string | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    let t: number;
    const run = async () => {
      try {
        const r = await fetch(apiUrl('/api/signal/current'));
        if (r.ok) {
          const j = (await r.json()) as SignalSnapshot;
          if (alive) {
            setSnap(j);
            if (j.current && j.current.timestamp !== lastTsRef.current) {
              lastTsRef.current = j.current.timestamp;
              phaseStartRef.current = Date.now();
            }
          }
        }
      } catch {
        /* ignore */
      }
      if (alive) t = window.setTimeout(run, 400);
    };
    run();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => tick((n) => n + 1), 100);
    return () => window.clearInterval(id);
  }, []);

  const plan = snap?.plan;
  const cur = snap?.current ?? null;
  const threePhase = plan?.mode === 'three_phase';
  const dur = cur?.duration_seconds ?? 1;
  const elapsed = Math.min(
    dur,
    (Date.now() - (phaseStartRef.current ?? Date.now())) / 1000,
  );
  const pct = Math.max(0, Math.min(100, (elapsed / dur) * 100));
  const remain = Math.max(0, dur - elapsed);
  const activePhase = cur?.phase_name;

  const rows = threePhase
    ? [
        { label: 'NS', sub: '(N+S)' },
        { label: 'E', sub: '' },
        { label: 'W', sub: '' },
      ]
    : [
        { label: 'NS', sub: '(N+S)' },
        { label: 'EW', sub: '(E+W)' },
      ];

  const planLine = plan
    ? threePhase
      ? `cycle ${plan.cycle_seconds}s · NS ${plan.NS_green}s · E ${plan.E_green ?? plan.NS_green}s · W ${plan.W_green ?? plan.NS_green}s · yellow ${plan.yellow}s · all-red ${plan.all_red}s`
      : `cycle ${plan.cycle_seconds}s · NS ${plan.NS_green}s · EW ${plan.EW_green}s · yellow ${plan.yellow}s · all-red ${plan.all_red}s`
    : '—';

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
          marginBottom: 4,
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
          Live signal state
        </div>
        <div
          style={{
            font: '500 10px var(--mono)',
            color: 'var(--fg-faint)',
          }}
        >
          cycle #{cur?.cycle_number ?? '—'}{' '}
          {cur?.video_ts_seconds != null
            ? `· video t=${cur.video_ts_seconds.toFixed(1)}s`
            : ''}
        </div>
      </div>
      <div style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)', marginBottom: 12 }}>
        {planLine}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map((r) => {
          const isActive = activePhase === r.label;
          const state = isActive ? cur!.signal_state : 'RED ON';
          const dot = STATE_DOT[state as keyof typeof STATE_DOT] ?? '#444';
          const phaseColor = PHASE_COLOR[r.label as keyof typeof PHASE_COLOR] ?? '#888';
          return (
            <div
              key={r.label}
              style={{
                display: 'grid',
                gridTemplateColumns: '74px 90px 1fr 70px',
                gap: 10,
                alignItems: 'center',
              }}
            >
              <div>
                <span
                  style={{
                    font: '700 13px var(--mono)',
                    color: phaseColor,
                  }}
                >
                  {r.label}
                </span>
                {r.sub && (
                  <span
                    style={{
                      font: '500 10px var(--mono)',
                      color: 'var(--fg-faint)',
                      marginLeft: 6,
                    }}
                  >
                    {r.sub}
                  </span>
                )}
              </div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  font: '600 11px var(--mono)',
                  color: isActive ? dot : 'var(--fg-faint)',
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: dot,
                    opacity: isActive ? 1 : 0.4,
                  }}
                />
                {state}
              </div>
              <div
                style={{
                  height: 8,
                  background: 'var(--surface)',
                  borderRadius: 4,
                  overflow: 'hidden',
                  border: '1px solid var(--border-soft)',
                }}
              >
                <div
                  style={{
                    width: `${isActive ? pct : 0}%`,
                    height: '100%',
                    background: phaseColor,
                    transition: 'width 0.1s linear',
                  }}
                />
              </div>
              <div
                style={{
                  font: '500 11px var(--mono)',
                  color: 'var(--fg-dim)',
                  textAlign: 'right',
                }}
              >
                {isActive ? `${remain.toFixed(1)}s` : '—'}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
