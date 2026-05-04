import { useEffect, useState } from 'react';
import { apiUrl } from '../../api/client';

interface EventRecord {
  ts: string;
  event_id: string;
  event_type: string;
  approach: string | null;
  severity: string;
  confidence: number;
  payload: Record<string, unknown>;
  snapshot_uri?: string;
  snapshot_stale?: boolean;
}

const SEVERITY_TONE: Record<string, string> = {
  critical: 'var(--bad)',
  warning: 'var(--accent)',
  info: 'var(--good)',
};

const EVENT_LABEL: Record<string, string> = {
  congestion_class_change: 'congestion shift',
  queue_spillback: 'queue spillback',
  abnormal_stopping: 'abnormal stop',
  stalled_vehicle: 'stalled veh',
  wrong_way: 'wrong way',
};

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

function summarisePayload(ev: EventRecord): string {
  const p = ev.payload || {};
  switch (ev.event_type) {
    case 'wrong_way':
      return `track #${p.track_id} · ${(p.speed_px_per_s as number)?.toFixed(0) ?? '?'} px/s · expected ${p.expected_direction}`;
    case 'stalled_vehicle':
      return `track #${p.track_id} · ${(p.stationary_seconds as number)?.toFixed(1) ?? '?'}s stationary`;
    case 'abnormal_stopping':
      return `track #${p.track_id} · ${(p.stationary_seconds as number)?.toFixed(1) ?? '?'}s in ${p.signal_phase ?? '?'} ${p.signal_state ?? ''}`;
    case 'queue_spillback':
      return `${p.queue_count} veh · threshold ${p.threshold} · ${(p.duration_s as number)?.toFixed(1) ?? '?'}s`;
    case 'congestion_class_change':
      return `${p.from} → ${p.to} · pressure ${(p.pressure as number)?.toFixed(1) ?? '?'}`;
    default:
      return JSON.stringify(p).slice(0, 80);
  }
}

export function LiveEventsPanel() {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(apiUrl('/api/events?limit=20'));
        if (r.ok) {
          const j = (await r.json()) as { events: EventRecord[] };
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
          Live events · §6.6
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
          gap: 4,
          maxHeight: 320,
          overflowY: 'auto',
        }}
      >
        {events.length === 0 && (
          <div style={{ font: '400 11px var(--mono)', color: 'var(--fg-faint)' }}>
            no events yet
          </div>
        )}
        {events
          .slice()
          .reverse()
          .map((ev) => (
            <div
              key={ev.event_id}
              style={{
                display: 'grid',
                gridTemplateColumns: '64px 22px 110px 1fr',
                gap: 8,
                alignItems: 'baseline',
                padding: '4px 6px',
                borderLeft: `2px solid ${SEVERITY_TONE[ev.severity] ?? 'var(--fg-faint)'}`,
                background: 'rgba(255,255,255,0.015)',
                borderRadius: 4,
              }}
            >
              <span style={{ font: '500 10px var(--mono)', color: 'var(--fg-faint)' }}>
                {formatTs(ev.ts)}
              </span>
              <span
                style={{
                  font: '700 11px var(--mono)',
                  color: SEVERITY_TONE[ev.severity] ?? 'var(--fg)',
                }}
              >
                {ev.approach ?? '·'}
              </span>
              <span
                style={{
                  font: '600 11px var(--mono)',
                  color: 'var(--fg)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}
              >
                {EVENT_LABEL[ev.event_type] ?? ev.event_type}
              </span>
              <span style={{ font: '400 11px var(--mono)', color: 'var(--fg-dim)' }}>
                {summarisePayload(ev)}
              </span>
            </div>
          ))}
      </div>
    </div>
  );
}
