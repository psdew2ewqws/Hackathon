import { useEffect, useMemo, useState } from 'react';
import { apiUrl, getRecommendation } from '../../api/client';

interface BackendInfo {
  active: string;
  available: string[];
  loaded: string[];
  pending: string | null;
  label: string;
}

interface ForecastMl {
  available: boolean;
  per_detector?: Record<string, unknown>;
  target_ts?: string;
}

interface Health {
  tracker?: { running: boolean; fps: number };
}

interface LlmStatus {
  available?: boolean;
  model?: string;
  tools?: number;
  message?: string;
}

type Status = 'active' | 'idle' | 'warming' | 'error';

interface AIBlockProps {
  family: 'detection' | 'tracking' | 'forecast' | 'optimizer' | 'advisor';
  name: string;
  arch: string;
  metric: string;
  metricValue: string;
  why: string;
  status: Status;
  action?: { label: string; onClick: () => void; disabled?: boolean };
  highlight?: boolean;
}

const STATUS_COLOR: Record<Status, string> = {
  active: 'var(--good)',
  idle: 'var(--fg-faint)',
  warming: 'var(--accent)',
  error: 'var(--bad)',
};

const FAMILY_TAG: Record<AIBlockProps['family'], string> = {
  detection: 'DETECTION',
  tracking: 'TRACKING',
  forecast: 'FORECAST',
  optimizer: 'OPTIMIZER',
  advisor: 'ADVISOR',
};

const FAMILY_HUE: Record<AIBlockProps['family'], string> = {
  detection: 'var(--ai)',
  tracking: 'var(--accent)',
  forecast: '#a78bfa',
  optimizer: '#7FA889',
  advisor: '#f0a5d4',
};

function AIBlock({
  family,
  name,
  arch,
  metric,
  metricValue,
  why,
  status,
  action,
  highlight,
}: AIBlockProps) {
  const dot = STATUS_COLOR[status];
  const familyHue = FAMILY_HUE[family];
  return (
    <div
      style={{
        position: 'relative',
        background: highlight
          ? 'linear-gradient(180deg, rgba(255,177,0,0.06), rgba(255,177,0,0.01))'
          : 'var(--surface)',
        border: '1px solid',
        borderColor: highlight ? 'var(--accent-soft)' : 'var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '12px 14px',
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
          background: familyHue,
          opacity: status === 'active' ? 1 : 0.3,
        }}
      />
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 6,
        }}
      >
        <span
          style={{
            font: '600 9px var(--mono)',
            letterSpacing: '0.18em',
            color: familyHue,
            textTransform: 'uppercase',
          }}
        >
          {FAMILY_TAG[family]}
        </span>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            font: '500 9px var(--mono)',
            color: dot,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
          }}
        >
          <span
            className={status === 'active' ? 'dot-pulse' : ''}
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: dot,
              boxShadow: status === 'active' ? `0 0 8px ${dot}` : 'none',
              display: 'inline-block',
            }}
          />
          {status}
        </span>
      </div>

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
            font: '600 16px var(--sans)',
            color: 'var(--fg)',
            letterSpacing: '-0.01em',
            lineHeight: 1.05,
          }}
        >
          {name}
        </div>
        <div
          style={{
            font: '600 14px var(--mono)',
            color: status === 'active' ? 'var(--fg)' : 'var(--fg-dim)',
            letterSpacing: '-0.01em',
          }}
        >
          {metricValue}
        </div>
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          font: '500 10px var(--mono)',
          color: 'var(--fg-faint)',
          letterSpacing: '0.04em',
          marginBottom: 8,
        }}
      >
        <span>{arch}</span>
        <span>{metric}</span>
      </div>

      <div
        style={{
          font: '400 11.5px var(--sans)',
          color: 'var(--fg-dim)',
          lineHeight: 1.45,
          marginBottom: action ? 10 : 0,
        }}
      >
        <span style={{ color: 'var(--fg-faint)' }}>why · </span>
        {why}
      </div>

      {action && (
        <button
          type="button"
          onClick={action.onClick}
          disabled={action.disabled}
          style={{
            font: '500 10px var(--mono)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: action.disabled ? 'var(--fg-faint)' : 'var(--fg)',
            background: action.disabled ? 'transparent' : 'var(--surface-3)',
            border: '1px solid',
            borderColor: action.disabled ? 'var(--border-soft)' : 'var(--border)',
            borderRadius: 6,
            padding: '5px 11px',
            cursor: action.disabled ? 'not-allowed' : 'pointer',
            opacity: action.disabled ? 0.6 : 1,
          }}
        >
          {action.label}
        </button>
      )}
    </div>
  );
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

export function AIStackPanel() {
  const [backend, setBackend] = useState<BackendInfo | null>(null);
  const [forecast, setForecast] = useState<ForecastMl | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const [delayPct, setDelayPct] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

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
      } catch {
        /* keep last good */
      }
    };
    tick();
    const id = window.setInterval(tick, 2500);
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

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '14px 14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        height: '100%',
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
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: 'var(--fg-bright)',
          }}
        >
          AI inference stack
        </div>
        <div
          style={{
            font: '500 10px var(--mono)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--ai)',
          }}
        >
          6 models · live
        </div>
      </div>

      <AIBlock
        family="detection"
        name="RF-DETR base"
        arch="DETR transformer · 32M params"
        metric="COCO mAP"
        metricValue="0.51"
        why="catches small / partially-occluded vehicles where convnets miss; transformer attention reads dense scenes well."
        status={rfdetrActive ? 'active' : backend?.pending === 'rfdetr' ? 'warming' : 'idle'}
        highlight={rfdetrActive}
        action={{
          label: rfdetrActive ? 'in use' : busy === 'rfdetr' ? 'loading…' : 'switch to RF-DETR',
          disabled: rfdetrActive || !!busy,
          onClick: () => switchBackend('rfdetr'),
        }}
      />

      <AIBlock
        family="detection"
        name="YOLO 26n"
        arch="convnet · 4M params"
        metric="COCO mAP"
        metricValue="0.41"
        why="real-time fallback when latency budget shrinks; ~7× faster than RF-DETR on the same GPU."
        status={yoloActive ? 'active' : backend?.pending === 'ultralytics' ? 'warming' : 'idle'}
        highlight={yoloActive}
        action={{
          label: yoloActive ? 'in use' : busy === 'ultralytics' ? 'loading…' : 'switch to YOLO',
          disabled: yoloActive || !!busy,
          onClick: () => switchBackend('ultralytics'),
        }}
      />

      <AIBlock
        family="tracking"
        name="ByteTrack"
        arch="motion + IoU association"
        metric="live fps"
        metricValue={fps > 0 ? fps.toFixed(1) : '—'}
        why="assigns persistent IDs so a single car crossing the stop-line is counted once, not per frame."
        status={fps > 0 ? 'active' : 'idle'}
      />

      <AIBlock
        family="forecast"
        name="LightGBM"
        arch="gradient boosting · per-detector"
        metric="MAE @ 15min"
        metricValue="6.2"
        why={`predicts demand 0–60 min ahead from ${detectorCount} detector lanes; feeds the +1h Webster recommendation.`}
        status={forecast?.available ? 'active' : 'idle'}
      />

      <AIBlock
        family="optimizer"
        name="Webster · HCM"
        arch="3-phase rule-based"
        metric="delay Δ"
        metricValue={delayPct == null ? '—' : `${delayPct >= 0 ? '−' : '+'}${Math.abs(delayPct).toFixed(0)}%`}
        why="closed-form green-time split that minimises uniform delay given the live + forecast flow ratios."
        status={delayPct != null ? 'active' : 'idle'}
      />

      <AIBlock
        family="advisor"
        name="Claude · MCP"
        arch={llm?.model ? `${llm.model}` : 'opus / sonnet'}
        metric="tools"
        metricValue={llm?.tools != null ? String(llm.tools) : '8'}
        why="answers natural-language questions by calling MCP tools (current state, history, typical-day, recommendations)."
        status={llm?.available ? 'active' : 'idle'}
      />
    </div>
  );
}
