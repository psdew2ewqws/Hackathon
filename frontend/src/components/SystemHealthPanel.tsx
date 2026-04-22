import { useEffect, useState } from 'react';

interface RtspProbe {
  healthy?: boolean;
  codec?: string;
  width?: number;
  height?: number;
  fps?: number;
  failures?: string[];
  url?: string;
  error?: string;
}

interface HealthResponse {
  available: boolean;
  viewer_uptime_s?: number;
  phase2_alive?: boolean;
  phase2_pid?: number;
  phase2_fps?: number | null;
  events_age_s?: number;
  events_size_bytes?: number;
  ffmpeg_alive?: boolean;
  rtsp?: RtspProbe;
}

function fmtUptime(s: number): string {
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 ** 3) return `${(b / 1024 / 1024).toFixed(1)} MB`;
  return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

function Tile({
  label,
  value,
  ok,
  detail,
}: {
  label: string;
  value: string;
  ok: boolean | null;
  detail?: string;
}) {
  const okColor =
    ok === null
      ? 'var(--fg-mute)'
      : ok
        ? 'var(--good)'
        : 'var(--bad)';
  return (
    <div
      style={{
        padding: '12px 14px',
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-md)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          font: '500 10px var(--mono)',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
          marginBottom: 6,
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: okColor,
            boxShadow: ok ? `0 0 5px ${okColor}80` : 'none',
            display: 'inline-block',
          }}
        />
        {label}
      </div>
      <div
        style={{
          font: '600 18px var(--mono)',
          color: 'var(--fg)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </div>
      {detail && (
        <div
          style={{
            font: '400 10px var(--mono)',
            color: 'var(--fg-dim)',
            marginTop: 4,
          }}
        >
          {detail}
        </div>
      )}
    </div>
  );
}

export function SystemHealthPanel() {
  const [data, setData] = useState<HealthResponse | null>(null);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const r = await fetch('/api/health');
        const j = (await r.json()) as HealthResponse;
        setData(j);
      } catch {
        // ignore
      }
    };
    fetchHealth();
    const id = window.setInterval(fetchHealth, 5000);
    return () => window.clearInterval(id);
  }, []);

  const rtsp = data?.rtsp;
  const eventsFresh =
    data?.events_age_s !== undefined && data.events_age_s < 5;

  return (
    <section
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-md)',
        padding: '20px 22px',
        marginTop: 20,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 14,
        }}
      >
        <div>
          <h2
            style={{
              font: '500 13px var(--sans)',
              color: 'var(--fg)',
              margin: '0 0 6px',
            }}
          >
            System health
          </h2>
          <p
            style={{
              font: '400 11px var(--mono)',
              color: 'var(--fg-faint)',
              margin: 0,
            }}
          >
            polled every 5 s · ingestion rate · YOLO FPS · stream uptime
          </p>
        </div>
        <span
          style={{
            font: '500 11px var(--mono)',
            color: 'var(--fg-faint)',
            letterSpacing: '0.02em',
          }}
        >
          /api/health
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 12,
        }}
      >
        <Tile
          label="Viewer uptime"
          value={
            data?.viewer_uptime_s !== undefined
              ? fmtUptime(data.viewer_uptime_s)
              : '—'
          }
          ok={data?.viewer_uptime_s !== undefined}
        />
        <Tile
          label="RTSP stream"
          value={
            rtsp?.healthy
              ? `${rtsp.codec ?? '—'} · ${rtsp.fps ?? '—'} fps`
              : 'down'
          }
          ok={rtsp?.healthy ?? null}
          detail={
            rtsp?.healthy
              ? `${rtsp.width}×${rtsp.height}`
              : rtsp?.error ?? rtsp?.failures?.join(', ')
          }
        />
        <Tile
          label="YOLO FPS"
          value={
            data?.phase2_fps != null
              ? `${data.phase2_fps.toFixed(1)} fps`
              : data?.phase2_alive
                ? 'warming up'
                : 'down'
          }
          ok={data?.phase2_alive ?? null}
          detail={
            data?.phase2_pid ? `pid ${data.phase2_pid}` : undefined
          }
        />
        <Tile
          label="Event log"
          value={
            data?.events_age_s != null
              ? `${data.events_age_s.toFixed(1)}s ago`
              : '—'
          }
          ok={eventsFresh}
          detail={
            data?.events_size_bytes
              ? fmtBytes(data.events_size_bytes)
              : undefined
          }
        />
      </div>
      <div
        style={{
          marginTop: 12,
          font: '400 11px var(--mono)',
          color: 'var(--fg-dim)',
        }}
      >
        ffmpeg publisher:{' '}
        <b
          style={{
            color: data?.ffmpeg_alive ? 'var(--good)' : 'var(--bad)',
          }}
        >
          {data?.ffmpeg_alive ? 'running' : 'stopped'}
        </b>
      </div>
    </section>
  );
}
