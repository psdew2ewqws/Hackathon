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
  pending: string | null;
  loaded: string[];
  label: string;
}

const BACKEND_NAME: Record<string, string> = {
  rfdetr: 'RF-DETR base',
  ultralytics: 'YOLO 26n',
};

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
        /* keep last good */
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
  const incidents = health?.storage?.incidents ?? 0;
  const cycleCounts = health?.storage?.counts ?? 0;
  const dotColor = running
    ? 'var(--good)'
    : backend?.pending
    ? 'var(--accent)'
    : 'var(--fg-faint)';
  const activeName = backend?.active ? BACKEND_NAME[backend.active] ?? backend.active : '—';
  const pendingName = backend?.pending ? BACKEND_NAME[backend.pending] : null;

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <span
            style={{
              font: '600 11px var(--mono)',
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-bright)',
            }}
          >
            Live feed
          </span>
          <span
            style={{
              font: '500 10px var(--mono)',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--fg-faint)',
            }}
          >
            wadi saqra · 848×478 · {pendingName ? `loading ${pendingName}` : activeName}
          </span>
        </div>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            font: '600 11px var(--mono)',
            color: dotColor,
            letterSpacing: '0.04em',
          }}
        >
          <span
            className={running ? 'dot-pulse' : ''}
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: dotColor,
              boxShadow: running ? `0 0 8px ${dotColor}` : 'none',
              display: 'inline-block',
            }}
          />
          {running ? `${fps.toFixed(1)} FPS` : pendingName ? 'WARMING' : 'IDLE'}
        </div>
      </div>

      <div
        className="scanlines"
        style={{
          position: 'relative',
          width: '100%',
          flex: '1 1 auto',
          background: '#000',
          borderRadius: 'var(--r-md)',
          overflow: 'hidden',
          aspectRatio: '848 / 478',
          border: '1px solid var(--border)',
          boxShadow: 'var(--shadow-1)',
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

        {/* Active-detector chip overlay */}
        <div
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '5px 10px',
            background: 'rgba(12, 13, 16, 0.78)',
            backdropFilter: 'blur(8px)',
            border: '1px solid rgba(255, 177, 0, 0.35)',
            borderRadius: 999,
            font: '600 10px var(--mono)',
            color: 'var(--accent)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
          }}
        >
          <span
            className="dot-pulse"
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: 'var(--accent)',
              boxShadow: '0 0 8px var(--accent)',
            }}
          />
          {activeName}
        </div>

        {/* Bottom telemetry strip */}
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: 0,
            padding: '10px 14px',
            background:
              'linear-gradient(180deg, transparent, rgba(12,13,16,0.85) 70%)',
            display: 'flex',
            justifyContent: 'space-between',
            font: '500 10px var(--mono)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: 'var(--fg-dim)',
          }}
        >
          <span>RTSP · 127.0.0.1:8554 / wadi_saqra</span>
          <span>
            {cycleCounts.toLocaleString()} bins · {incidents.toLocaleString()} incidents
          </span>
        </div>
      </div>

      {health?.tracker?.last_error && (
        <div
          style={{
            marginTop: 10,
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
