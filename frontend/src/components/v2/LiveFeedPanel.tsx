import { useEffect, useState } from 'react';
import { apiUrl } from '../../api/client';

interface HealthSnapshot {
  tracker?: { running: boolean; fps: number; last_error: string | null };
  signal_sim?: { running: boolean };
  storage?: { counts: number; signals: number; incidents: number };
  sink_queue?: number | null;
}

interface BackendInfo {
  active: string;
  label: string;
  pending: string | null;
}

export function LiveFeedPanel() {
  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const [backend, setBackend] = useState<BackendInfo | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [h, b] = await Promise.all([
          fetch(apiUrl('/api/health')).then((r) => (r.ok ? r.json() : null)),
          fetch(apiUrl('/api/tracker/backend')).then((r) =>
            r.ok ? r.json() : null,
          ),
        ]);
        if (!alive) return;
        if (h) setHealth(h);
        if (b) setBackend(b);
      } catch {
        /* next tick retries */
      }
    };
    tick();
    const id = window.setInterval(tick, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const fps = health?.tracker?.fps ?? 0;
  const running = !!health?.tracker?.running;
  const dotColor = running ? 'var(--good)' : 'var(--bad)';

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: 12,
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
          Annotated RTSP feed
        </div>
        <div
          style={{
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            font: '500 10px var(--mono)',
            color: 'var(--fg-faint)',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                background: dotColor,
                display: 'inline-block',
              }}
            />
            {running ? `${fps.toFixed(1)} fps` : 'idle'}
          </span>
          {backend?.label && (
            <span style={{ color: 'var(--accent)' }}>{backend.label}</span>
          )}
        </div>
      </div>

      <div
        style={{
          position: 'relative',
          width: '100%',
          background: '#000',
          borderRadius: 6,
          overflow: 'hidden',
          aspectRatio: '848 / 478',
        }}
      >
        <img
          src={apiUrl('/mjpeg')}
          alt="annotated tracker feed"
          style={{
            width: '100%',
            height: '100%',
            display: 'block',
            objectFit: 'cover',
          }}
        />
      </div>

      {health?.tracker?.last_error && (
        <div
          style={{
            marginTop: 8,
            font: '500 11px var(--mono)',
            color: 'var(--bad)',
          }}
        >
          {health.tracker.last_error}
        </div>
      )}
    </div>
  );
}
