import { useEffect, useState } from 'react';
import { apiUrl } from '../../api/client';

interface SignalLogEntry {
  timestamp: string;
  cycle_number: number;
  phase_number: number;
  phase_name: string;
  signal_state: string;
  approaches_affected: string[];
  duration_seconds: number;
  source?: string;
  video_ts_seconds?: number;
}

const PHASE_COLOR: Record<string, string> = {
  NS: '#6FA8D6',
  E: '#7FA889',
  W: '#C583C5',
  EW: '#E8B464',
};

const STATE_TONE: Record<string, string> = {
  'GREEN ON': 'var(--good)',
  'YELLOW ON': 'var(--accent)',
  'RED ON': 'var(--fg-faint)',
};

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

export function RecentSignalPanel() {
  const [events, setEvents] = useState<SignalLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(apiUrl('/api/signal/log?limit=24'));
        if (r.ok) {
          const j = (await r.json()) as { events: SignalLogEntry[] };
          if (alive) {
            setEvents(j.events ?? []);
            setError(null);
          }
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    tick();
    const id = window.setInterval(tick, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '14px 16px',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
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
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--fg-dim)',
          }}
        >
          Recent signal events
        </div>
        <div style={{ font: '500 10px var(--mono)', color: 'var(--fg-faint)' }}>
          last {events.length}
        </div>
      </div>

      {error && (
        <div style={{ font: '500 11px var(--mono)', color: 'var(--bad)' }}>{error}</div>
      )}

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 3,
          maxHeight: 320,
          overflowY: 'auto',
        }}
      >
        {events
          .slice()
          .reverse()
          .map((ev, i) => {
            const color = PHASE_COLOR[ev.phase_name] ?? '#888';
            const tone = STATE_TONE[ev.signal_state] ?? 'var(--fg)';
            return (
              <div
                key={`${ev.timestamp}-${i}`}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '64px 36px 90px 50px 1fr',
                  gap: 8,
                  alignItems: 'baseline',
                  padding: '3px 6px',
                  borderLeft: `2px solid ${color}`,
                  background: 'rgba(255,255,255,0.015)',
                  borderRadius: 4,
                }}
              >
                <span style={{ font: '500 10px var(--mono)', color: 'var(--fg-faint)' }}>
                  {formatTs(ev.timestamp)}
                </span>
                <span style={{ font: '700 11px var(--mono)', color }}>
                  {ev.phase_name}
                </span>
                <span style={{ font: '600 11px var(--mono)', color: tone }}>
                  {ev.signal_state}
                </span>
                <span style={{ font: '500 11px var(--mono)', color: 'var(--fg-faint)' }}>
                  {ev.duration_seconds.toFixed(0)}s
                </span>
                <span style={{ font: '400 10px var(--mono)', color: 'var(--fg-faint)' }}>
                  cycle #{ev.cycle_number}
                </span>
              </div>
            );
          })}
      </div>
    </div>
  );
}
