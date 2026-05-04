import { useEffect, useMemo, useRef, useState } from 'react';
import { apiUrl, getRecommendation } from '../../api/client';
import {
  APPROACHES,
  APPROACH_COLOR,
  type Approach,
} from '../../api/types';

interface BackendInfo {
  active: string;
  available: string[];
  loaded: string[];
  pending: string | null;
  label: string;
}

interface ForecastMl {
  available: boolean;
  per_detector?: Record<string, { approach: Approach; y_now: number; y_60min: number }>;
  target_ts?: string;
}

interface Health {
  tracker?: { running: boolean; fps: number };
}

interface LlmStatus {
  available?: boolean;
  configured?: boolean;
  model?: string;
  tools?: number;
}

async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
  const t = localStorage.getItem('traffic_intel_token');
  return fetch(apiUrl(path), {
    ...init,
    headers: {
      ...(init?.headers || {}),
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    },
  });
}

const FAMILY_HUE = {
  detection: 'var(--ai)',
  tracking: 'var(--accent)',
  forecast: '#a78bfa',
  optimizer: 'var(--good)',
  advisor: '#f0a5d4',
} as const;

export function AIStackPanel() {
  const [backend, setBackend] = useState<BackendInfo | null>(null);
  const [forecast, setForecast] = useState<ForecastMl | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const [delayPct, setDelayPct] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Trailing fps history for the tracking row spark.
  const fpsHistRef = useRef<number[]>([]);
  const [fpsTick, setFpsTick] = useState(0);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [b, f, h, l, r] = await Promise.all([
          fetch(apiUrl('/api/tracker/backend')).then((r) => (r.ok ? r.json() : null)),
          fetch(apiUrl('/api/forecast/ml')).then((r) => (r.ok ? r.json() : null)),
          fetch(apiUrl('/api/health')).then((r) => (r.ok ? r.json() : null)),
          authedFetch('/api/llm/status').then((r) => (r.ok ? r.json() : null)),
          getRecommendation().catch(() => null),
        ]);
        if (!alive) return;
        if (b) setBackend(b);
        if (f) setForecast(f);
        if (h) setHealth(h);
        if (l) setLlm(l);
        if (r) setDelayPct(r.recommendation?.comparison?.delay_reduction_pct ?? null);
        const fps = h?.tracker?.fps ?? 0;
        const arr = fpsHistRef.current;
        arr.push(fps);
        if (arr.length > 30) arr.shift();
        setFpsTick((n) => n + 1);
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

  const switchBackend = async (name: string) => {
    if (busy || !backend || backend.active === name) return;
    setBusy(name);
    try {
      await authedFetch('/api/tracker/backend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend: name }),
      });
    } finally {
      setBusy(null);
    }
  };

  const rfdetrActive = backend?.active === 'rfdetr';
  const yoloActive = backend?.active === 'ultralytics';
  const fps = health?.tracker?.fps ?? 0;
  const detectorCount = useMemo(
    () => Object.keys(forecast?.per_detector ?? {}).length,
    [forecast],
  );

  // Aggregate per-approach demand for the forecast row
  const perApproach = useMemo(() => {
    const sums: Record<Approach, { now: number; future: number }> = {
      S: { now: 0, future: 0 },
      N: { now: 0, future: 0 },
      E: { now: 0, future: 0 },
      W: { now: 0, future: 0 },
    };
    for (const det of Object.values(forecast?.per_detector ?? {})) {
      const a = det.approach as Approach;
      if (sums[a]) {
        sums[a].now += det.y_now;
        sums[a].future += det.y_60min;
      }
    }
    return sums;
  }, [forecast]);

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '12px 14px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          paddingBottom: 8,
          borderBottom: '1px solid var(--border-soft)',
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
          AI inference · live
        </div>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            font: '500 10px var(--mono)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--ai)',
          }}
        >
          <span
            className="dot-pulse"
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: 'var(--ai)',
              boxShadow: '0 0 6px var(--ai)',
            }}
          />
          6 models · {Object.values(perApproach).reduce((s, p) => s + p.now, 0).toFixed(0)} veh/15m through
        </div>
      </div>

      {/* ─── DETECTOR BATTLE ─── */}
      <SectionLabel hue={FAMILY_HUE.detection} family="DETECTION" sub="choose your tradeoff" />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 8,
        }}
      >
        <DetectorCard
          name="RF-DETR base"
          arch="DETR transformer"
          mAP={0.51}
          params={32}
          latency={120}
          rationale="catches small / occluded vehicles"
          active={rfdetrActive}
          warming={backend?.pending === 'rfdetr'}
          busy={busy}
          onSwitch={() => switchBackend('rfdetr')}
        />
        <DetectorCard
          name="YOLO 26n"
          arch="convnet"
          mAP={0.41}
          params={4}
          latency={16}
          rationale="real-time fallback · ~7× faster"
          active={yoloActive}
          warming={backend?.pending === 'ultralytics'}
          busy={busy}
          onSwitch={() => switchBackend('ultralytics')}
        />
      </div>

      {/* ─── TRACKING ─── */}
      <SectionLabel hue={FAMILY_HUE.tracking} family="TRACKING" sub="ByteTrack · IoU + motion" />
      <Row hue={FAMILY_HUE.tracking}>
        <RowLabel main="ByteTrack" sub="persistent IDs · counted once across stop-line" />
        <Spark values={fpsHistRef.current} hue={FAMILY_HUE.tracking} />
        <RowMetric value={fps > 0 ? fps.toFixed(1) : '—'} unit="fps" />
      </Row>

      {/* ─── FORECAST ─── */}
      <SectionLabel hue={FAMILY_HUE.forecast} family="FORECAST" sub="LightGBM · 22 detectors · 4 horizons" />
      <Row hue={FAMILY_HUE.forecast}>
        <RowLabel main="LightGBM" sub={`MAE 6.2 @ 15min · ${detectorCount} detector lanes`} />
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 6,
            flex: 1,
          }}
        >
          {APPROACHES.map((a) => {
            const v = perApproach[a as Approach];
            const dlt = v.now > 0 ? ((v.future - v.now) / v.now) * 100 : 0;
            const tone =
              dlt > 8 ? 'var(--bad)' : dlt < -8 ? 'var(--good)' : 'var(--fg-dim)';
            const arrow = dlt > 8 ? '↑' : dlt < -8 ? '↓' : '→';
            return (
              <div
                key={a}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '14px 1fr',
                  alignItems: 'baseline',
                  gap: 4,
                }}
              >
                <span
                  style={{
                    font: '700 11px var(--mono)',
                    color: APPROACH_COLOR[a as Approach],
                  }}
                >
                  {a}
                </span>
                <span
                  className="tabular"
                  style={{
                    font: '500 10.5px var(--mono)',
                    color: tone,
                  }}
                >
                  {v.now.toFixed(0)}
                  <span style={{ color: 'var(--fg-mute)', margin: '0 3px' }}>
                    {arrow}
                  </span>
                  {v.future.toFixed(0)}
                </span>
              </div>
            );
          })}
        </div>
        <RowMetric
          value={detectorCount > 0 ? '+1h' : '—'}
          unit="ahead"
        />
      </Row>

      {/* ─── OPTIMIZER ─── */}
      <SectionLabel hue={FAMILY_HUE.optimizer} family="OPTIMIZER" sub="Webster · HCM · 3-phase" />
      <Row hue={FAMILY_HUE.optimizer}>
        <RowLabel
          main="Webster · HCM"
          sub="closed-form green-time minimising uniform delay"
        />
        <DelayBar pct={delayPct} />
        <RowMetric
          value={
            delayPct == null
              ? '—'
              : `${delayPct >= 0 ? '−' : '+'}${Math.abs(delayPct).toFixed(0)}%`
          }
          unit="delay"
          tone={delayPct == null ? undefined : delayPct >= 0 ? 'good' : 'warn'}
        />
      </Row>

      {/* ─── ADVISOR ─── */}
      <SectionLabel hue={FAMILY_HUE.advisor} family="ADVISOR" sub="natural-language → MCP tools" />
      <Row hue={FAMILY_HUE.advisor}>
        <RowLabel
          main="Claude · MCP"
          sub={`${llm?.model ?? 'opus / sonnet'} · ${llm?.configured ? 'ready' : 'offline'}`}
        />
        <ToolPalette />
        <RowMetric value={String(llm?.tools ?? 8)} unit="tools" />
      </Row>

      {/* hidden tick to force re-render of fps spark */}
      <span style={{ display: 'none' }}>{fpsTick}</span>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────── */
/*  Sub-components                                                    */
/* ────────────────────────────────────────────────────────────────── */

function SectionLabel({
  family,
  sub,
  hue,
}: {
  family: string;
  sub: string;
  hue: string;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 10,
        marginTop: 6,
      }}
    >
      <span
        style={{
          font: '700 9px var(--mono)',
          letterSpacing: '0.22em',
          color: hue,
        }}
      >
        {family}
      </span>
      <span
        style={{
          flex: 1,
          height: 1,
          background:
            'linear-gradient(90deg, var(--border-soft) 0%, transparent 100%)',
        }}
      />
      <span
        style={{
          font: '500 10px var(--mono)',
          letterSpacing: '0.04em',
          color: 'var(--fg-faint)',
        }}
      >
        {sub}
      </span>
    </div>
  );
}

function Row({
  hue,
  children,
}: {
  hue: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        position: 'relative',
        display: 'grid',
        gridTemplateColumns: 'minmax(140px, 1.1fr) 1.4fr auto',
        alignItems: 'center',
        gap: 12,
        padding: '8px 10px 8px 14px',
        background:
          'linear-gradient(90deg, rgba(255,255,255,0.015), transparent 60%)',
        border: '1px solid var(--border-soft)',
        borderLeft: `2px solid ${hue}`,
        borderRadius: 6,
      }}
    >
      {children}
    </div>
  );
}

function RowLabel({ main, sub }: { main: string; sub: string }) {
  return (
    <div>
      <div
        style={{
          font: '600 13.5px var(--sans)',
          color: 'var(--fg-bright)',
          letterSpacing: '-0.01em',
          marginBottom: 2,
        }}
      >
        {main}
      </div>
      <div
        style={{
          font: '500 10px var(--mono)',
          color: 'var(--fg-faint)',
          letterSpacing: '0.04em',
          lineHeight: 1.3,
        }}
      >
        {sub}
      </div>
    </div>
  );
}

function RowMetric({
  value,
  unit,
  tone,
}: {
  value: string;
  unit: string;
  tone?: 'good' | 'warn' | 'bad';
}) {
  const color =
    tone === 'good'
      ? 'var(--good)'
      : tone === 'warn'
      ? 'var(--warn)'
      : tone === 'bad'
      ? 'var(--bad)'
      : 'var(--fg-bright)';
  return (
    <div style={{ textAlign: 'right', minWidth: 64 }}>
      <div
        className="tabular"
        style={{
          font: '700 18px var(--sans)',
          color,
          letterSpacing: '-0.02em',
          lineHeight: 1,
        }}
      >
        {value}
      </div>
      <div
        style={{
          font: '500 9px var(--mono)',
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
          marginTop: 3,
        }}
      >
        {unit}
      </div>
    </div>
  );
}

function Spark({ values, hue }: { values: number[]; hue: string }) {
  if (values.length < 2) {
    return (
      <div
        style={{
          font: '500 10px var(--mono)',
          color: 'var(--fg-faint)',
          letterSpacing: '0.04em',
        }}
      >
        warming…
      </div>
    );
  }
  const W = 220;
  const H = 28;
  const max = Math.max(1, ...values);
  const xs = values.map((_, i) => (i / (values.length - 1)) * W);
  const ys = values.map((v) => H - (v / max) * H);
  const path = xs
    .map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${ys[i].toFixed(1)}`)
    .join(' ');
  const area = `${path} L${W},${H} L0,${H} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H }}>
      <path d={area} fill={hue} fillOpacity={0.12} />
      <path d={path} fill="none" stroke={hue} strokeWidth={1.5} />
    </svg>
  );
}

function DelayBar({ pct }: { pct: number | null }) {
  if (pct == null) return <div />;
  const reduction = Math.max(0, Math.min(100, pct));
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '60px 1fr 60px',
        gap: 8,
        alignItems: 'center',
      }}
    >
      <span
        style={{
          font: '500 10px var(--mono)',
          color: 'var(--fg-faint)',
          letterSpacing: '0.04em',
          textAlign: 'right',
        }}
      >
        current
      </span>
      <div
        style={{
          height: 8,
          background: 'var(--surface)',
          borderRadius: 4,
          position: 'relative',
          overflow: 'hidden',
          border: '1px solid var(--border-soft)',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            height: '100%',
            width: '100%',
            background: 'var(--surface-3)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            height: '100%',
            width: `${100 - reduction}%`,
            background:
              'linear-gradient(90deg, var(--good), rgba(110, 214, 143, 0.5))',
            transition: 'width 0.4s ease',
          }}
        />
      </div>
      <span
        style={{
          font: '500 10px var(--mono)',
          color: 'var(--good)',
          letterSpacing: '0.04em',
        }}
      >
        webster
      </span>
    </div>
  );
}

function ToolPalette() {
  const TOOLS = [
    { name: 'state', hue: 'var(--ai)' },
    { name: 'forecast', hue: '#a78bfa' },
    { name: 'history', hue: 'var(--fg-dim)' },
    { name: 'recom', hue: 'var(--good)' },
    { name: 'incidents', hue: 'var(--bad)' },
    { name: 'plan', hue: 'var(--accent)' },
    { name: 'typical', hue: '#a78bfa' },
    { name: 'sql', hue: 'var(--fg-dim)' },
  ];
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {TOOLS.map((t) => (
        <span
          key={t.name}
          style={{
            font: '500 9.5px var(--mono)',
            letterSpacing: '0.04em',
            color: t.hue,
            border: '1px solid var(--border-soft)',
            borderLeft: `2px solid ${t.hue}`,
            background: 'var(--surface)',
            padding: '2px 6px',
            borderRadius: 3,
          }}
        >
          {t.name}
        </span>
      ))}
    </div>
  );
}

function DetectorCard({
  name,
  arch,
  mAP,
  params,
  latency,
  rationale,
  active,
  warming,
  busy,
  onSwitch,
}: {
  name: string;
  arch: string;
  mAP: number;
  params: number;
  latency: number;
  rationale: string;
  active: boolean;
  warming: boolean;
  busy: string | null;
  onSwitch: () => void;
}) {
  const status = active ? 'active' : warming ? 'warming' : 'idle';
  const dot =
    status === 'active'
      ? 'var(--good)'
      : status === 'warming'
      ? 'var(--accent)'
      : 'var(--fg-faint)';
  // Visual scaling: mAP 0..1 → bar; params 0..40M → bar; latency 0..200ms → bar
  const mapPct = Math.min(100, mAP * 100);
  const paramPct = Math.min(100, (params / 40) * 100);
  const latPct = Math.min(100, (latency / 200) * 100);
  return (
    <div
      style={{
        position: 'relative',
        background: active
          ? 'linear-gradient(180deg, rgba(255,177,0,0.08), rgba(255,177,0,0.01))'
          : 'var(--surface)',
        border: '1px solid',
        borderColor: active ? 'var(--accent)' : 'var(--border-soft)',
        borderRadius: 6,
        padding: '10px 12px 11px',
        overflow: 'hidden',
      }}
    >
      {active && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            right: 0,
            font: '700 8.5px var(--mono)',
            letterSpacing: '0.18em',
            background: 'var(--accent)',
            color: '#0a0a0a',
            padding: '2px 8px 3px',
            borderRadius: '0 6px 0 6px',
          }}
        >
          IN USE
        </div>
      )}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
        }}
      >
        <div
          style={{
            font: '700 14px var(--sans)',
            color: 'var(--fg-bright)',
            letterSpacing: '-0.01em',
          }}
        >
          {name}
        </div>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            font: '500 9px var(--mono)',
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: dot,
          }}
        >
          <span
            className={status === 'active' ? 'dot-pulse' : ''}
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: dot,
              boxShadow: status === 'active' ? `0 0 6px ${dot}` : 'none',
            }}
          />
          {status}
        </span>
      </div>
      <div
        style={{
          font: '500 10px var(--mono)',
          color: 'var(--fg-faint)',
          letterSpacing: '0.04em',
          marginBottom: 10,
        }}
      >
        {arch} · {params}M params
      </div>

      <Bar label="mAP" value={mAP.toFixed(2)} pct={mapPct} hue={'var(--ai)'} />
      <Bar
        label="size"
        value={`${params}M`}
        pct={paramPct}
        hue={'var(--fg-dim)'}
      />
      <Bar
        label="latency"
        value={`~${latency}ms`}
        pct={latPct}
        hue={'var(--warn)'}
        invert
      />

      <div
        style={{
          font: '500 10.5px var(--sans)',
          color: 'var(--fg-dim)',
          letterSpacing: '0.005em',
          marginTop: 10,
          marginBottom: 10,
          lineHeight: 1.4,
        }}
      >
        {rationale}
      </div>

      <button
        type="button"
        onClick={onSwitch}
        disabled={active || !!busy}
        style={{
          width: '100%',
          font: '600 10px var(--mono)',
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: active
            ? 'var(--fg-faint)'
            : busy
            ? 'var(--fg-faint)'
            : 'var(--fg-bright)',
          background: active
            ? 'transparent'
            : busy
            ? 'var(--surface-3)'
            : 'var(--surface-3)',
          border: '1px solid',
          borderColor: active ? 'var(--border-soft)' : 'var(--border)',
          borderRadius: 5,
          padding: '6px 10px',
          cursor: active || busy ? 'not-allowed' : 'pointer',
        }}
      >
        {active ? '— in use —' : busy === name.toLowerCase() ? 'loading…' : 'switch to this'}
      </button>
    </div>
  );
}

function Bar({
  label,
  value,
  pct,
  hue,
  invert,
}: {
  label: string;
  value: string;
  pct: number;
  hue: string;
  invert?: boolean;
}) {
  // For latency, lower is better — reverse the visual fill direction.
  const w = invert ? Math.max(2, 100 - pct) : pct;
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '40px 1fr 50px',
        alignItems: 'center',
        gap: 8,
        marginBottom: 4,
      }}
    >
      <span
        style={{
          font: '500 9px var(--mono)',
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
        }}
      >
        {label}
      </span>
      <div
        style={{
          height: 5,
          background: 'var(--surface)',
          borderRadius: 3,
          overflow: 'hidden',
          border: '1px solid var(--border-soft)',
        }}
      >
        <div
          style={{
            width: `${w}%`,
            height: '100%',
            background: hue,
            opacity: 0.85,
            transition: 'width 0.4s',
          }}
        />
      </div>
      <span
        className="tabular"
        style={{
          font: '600 10px var(--mono)',
          color: 'var(--fg)',
          letterSpacing: '-0.01em',
          textAlign: 'right',
        }}
      >
        {value}
      </span>
    </div>
  );
}
