import { useEffect, useRef, useState } from 'react';
import {
  apiUrl,
  getCounts,
  getFusion,
  getSite,
  wsUrl,
} from '../api/client';
import {
  APPROACHES,
  type CountsResponse,
  type FusionResponse,
  type SiteConfig,
} from '../api/types';
import { ApproachCard } from '../components/ApproachCard';

// Order the right rail S, N, E, W as specified.
const CARD_ORDER = APPROACHES;

export function LivePage() {
  const [site, setSite] = useState<SiteConfig | null>(null);
  const [counts, setCounts] = useState<CountsResponse | null>(null);
  const [fusion, setFusion] = useState<FusionResponse | null>(null);
  const [wsStatus, setWsStatus] = useState<'connecting' | 'open' | 'closed'>(
    'connecting',
  );
  const wsRef = useRef<WebSocket | null>(null);

  // One-time site fetch
  useEffect(() => {
    const ac = new AbortController();
    getSite(ac.signal).then(setSite).catch(() => {});
    return () => ac.abort();
  }, []);

  // Poll counts + fusion each second
  useEffect(() => {
    let alive = true;
    let t: number;
    const tick = async () => {
      try {
        const [c, f] = await Promise.all([getCounts(), getFusion()]);
        if (!alive) return;
        setCounts(c);
        setFusion(f);
      } catch {
        /* ignored — next tick retries */
      }
      if (alive) t = window.setTimeout(tick, 1000);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  // WS: reconnect on close. We only use it as a bin-tick cue —
  // a fresh fetch keeps the UI authoritative.
  useEffect(() => {
    let closed = false;
    let retry: number;
    const connect = () => {
      const ws = new WebSocket(wsUrl('/ws/counts'));
      wsRef.current = ws;
      setWsStatus('connecting');
      ws.onopen = () => setWsStatus('open');
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg?.type === 'bin' && msg.record) {
            // Force an immediate counts refresh for the bin cue.
            getCounts().then(setCounts).catch(() => {});
          }
        } catch {
          /* non-JSON frame — ignore */
        }
      };
      ws.onclose = () => {
        setWsStatus('closed');
        if (!closed) retry = window.setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  const fused = fusion?.fused ?? ({} as FusionResponse['fused']);
  const capturedLocal = site?.video?.captured_at_local;
  const lat = site?.lat;
  const lng = site?.lng;

  return (
    <div style={{ padding: 14 }}>
      <TopBar
        counts={counts}
        wsStatus={wsStatus}
        capturedLocal={capturedLocal}
        lat={lat}
        lng={lng}
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.5fr) minmax(280px, 1fr)',
          gap: 14,
          marginTop: 14,
        }}
      >
        <section
          style={{
            background: '#121820',
            border: '1px solid #1e2630',
            borderRadius: 10,
            padding: 12,
          }}
        >
          <h2 style={cardTitle}>Annotated RTSP feed</h2>
          <img
            src={apiUrl('/mjpeg')}
            alt="live"
            style={{
              width: '100%',
              maxWidth: 960,
              aspectRatio: '16 / 9',
              display: 'block',
              background: '#000',
              borderRadius: 8,
              objectFit: 'cover',
            }}
          />
        </section>

        <section
          style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
        >
          {CARD_ORDER.map((a) => {
            const c = counts?.counts?.[a];
            const bin = counts?.crossings_in_current_bin?.[a] ?? 0;
            return (
              <ApproachCard
                key={a}
                approach={a}
                inZone={c?.in_zone ?? 0}
                crossingsTotal={c?.crossings_total ?? 0}
                crossingsInBin={bin}
                fused={fused[a]}
              />
            );
          })}
        </section>
      </div>
    </div>
  );
}

const cardTitle: React.CSSProperties = {
  fontSize: 12,
  margin: '0 0 10px',
  letterSpacing: '.06em',
  textTransform: 'uppercase',
  opacity: 0.7,
};

interface TopBarProps {
  counts: CountsResponse | null;
  wsStatus: 'connecting' | 'open' | 'closed';
  capturedLocal?: string;
  lat?: number;
  lng?: number;
}

function TopBar({ counts, wsStatus, capturedLocal, lat, lng }: TopBarProps) {
  const running = counts?.running;
  const fps = counts?.fps;
  const bin = counts?.bin_seconds;
  const err = counts?.last_error;
  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        flexWrap: 'wrap',
        alignItems: 'center',
        padding: '10px 14px',
        background: '#121820',
        border: '1px solid #1e2630',
        borderRadius: 10,
        fontSize: 13,
      }}
    >
      <span>
        <Dot color={running ? '#66ff88' : '#ff7a7a'} />
        <strong>{running ? 'live' : 'idle'}</strong>
      </span>
      <span style={{ opacity: 0.8 }}>
        {typeof fps === 'number' ? fps.toFixed(1) : '0.0'} FPS
      </span>
      <span style={{ opacity: 0.8 }}>bin {bin ?? '-'}s</span>
      <span style={{ opacity: 0.6 }}>
        ws: <em>{wsStatus}</em>
      </span>
      {capturedLocal && (
        <span style={{ opacity: 0.7 }}>
          captured&nbsp;
          <code style={{ fontSize: 12 }}>{capturedLocal}</code>
        </span>
      )}
      {lat != null && lng != null && (
        <span style={{ opacity: 0.6, marginLeft: 'auto' }}>
          {lat.toFixed(5)}, {lng.toFixed(5)}
        </span>
      )}
      {err && (
        <span
          style={{
            color: '#fecaca',
            background: '#7f1d1d',
            padding: '2px 8px',
            borderRadius: 6,
            fontSize: 12,
          }}
        >
          {err}
        </span>
      )}
    </div>
  );
}

function Dot({ color }: { color: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: 999,
        background: color,
        marginRight: 6,
      }}
    />
  );
}
