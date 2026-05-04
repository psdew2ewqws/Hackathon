import { useEffect, useState } from 'react';
import { apiUrl } from '../../api/client';

interface Stage {
  key: string;
  label: string;
  detail: string;
  hue: string;
}

const STAGES: Stage[] = [
  {
    key: 'rtsp',
    label: 'RTSP ingest',
    detail: 'mediamtx · 30 fps',
    hue: 'var(--fg-dim)',
  },
  {
    key: 'detect',
    label: 'detection',
    detail: 'RF-DETR / YOLO',
    hue: 'var(--ai)',
  },
  {
    key: 'track',
    label: 'tracking',
    detail: 'ByteTrack',
    hue: 'var(--accent)',
  },
  {
    key: 'count',
    label: 'zone counts',
    detail: 'PCE-aware',
    hue: 'var(--fg-dim)',
  },
  {
    key: 'fuse',
    label: 'fusion',
    detail: 'gmaps × actual',
    hue: '#a78bfa',
  },
  {
    key: 'forecast',
    label: 'forecast',
    detail: 'LightGBM',
    hue: '#a78bfa',
  },
  {
    key: 'optimize',
    label: 'optimise',
    detail: 'Webster · HCM',
    hue: '#7FA889',
  },
  {
    key: 'advise',
    label: 'advisor',
    detail: 'Claude · MCP',
    hue: '#f0a5d4',
  },
];

interface Health {
  tracker?: { running: boolean; fps: number };
  signal_sim?: { running: boolean };
  storage?: { counts: number; signals: number; incidents: number };
  sink_queue?: number | null;
}

export function AIPipelineStrip() {
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(apiUrl('/api/health'));
        if (r.ok) {
          const j = (await r.json()) as Health;
          if (alive) setHealth(j);
        }
      } catch {
        /* ignore */
      }
    };
    tick();
    const id = window.setInterval(tick, 2500);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const fps = health?.tracker?.fps ?? 0;
  const queueDepth = health?.sink_queue ?? 0;
  const counts = health?.storage?.counts ?? 0;

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '14px 18px',
        marginBottom: 14,
        position: 'relative',
        overflow: 'hidden',
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
        <div>
          <span
            style={{
              font: 'italic 400 18px var(--display)',
              color: 'var(--fg)',
              letterSpacing: '-0.01em',
            }}
          >
            Inference pipeline
          </span>
          <span
            style={{
              font: '500 9px var(--mono)',
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: 'var(--fg-faint)',
              marginLeft: 14,
            }}
          >
            video frame → operator decision
          </span>
        </div>
        <div
          style={{
            font: '500 10px var(--mono)',
            color: 'var(--fg-faint)',
            letterSpacing: '0.06em',
          }}
        >
          {fps > 0 ? `${fps.toFixed(1)} fps` : 'idle'} · queue {queueDepth} · {counts.toLocaleString()} bins
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${STAGES.length}, 1fr)`,
          alignItems: 'stretch',
          position: 'relative',
        }}
      >
        {/* horizontal connector under all stages */}
        <div
          style={{
            position: 'absolute',
            left: 14,
            right: 14,
            top: 12,
            height: 1,
            background:
              'linear-gradient(90deg, transparent 0%, var(--border) 8%, var(--border) 92%, transparent 100%)',
          }}
        />
        {STAGES.map((s, i) => (
          <div
            key={s.key}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-start',
              padding: '0 8px',
              position: 'relative',
              zIndex: 1,
            }}
          >
            <div
              style={{
                width: 18,
                height: 18,
                borderRadius: '50%',
                border: '1.5px solid',
                borderColor: s.hue,
                background: 'var(--bg)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: 8,
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: s.hue,
                  boxShadow: `0 0 8px ${s.hue}`,
                }}
              />
            </div>
            <div
              style={{
                font: '500 9px var(--mono)',
                color: 'var(--fg-faint)',
                letterSpacing: '0.16em',
                textTransform: 'uppercase',
                marginBottom: 1,
              }}
            >
              {String(i + 1).padStart(2, '0')}
            </div>
            <div
              style={{
                font: '600 12px var(--mono)',
                color: 'var(--fg)',
                letterSpacing: '0.02em',
                marginBottom: 1,
              }}
            >
              {s.label}
            </div>
            <div
              style={{
                font: '400 11px var(--mono)',
                color: 'var(--fg-faint)',
                letterSpacing: '0.02em',
              }}
            >
              {s.detail}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
