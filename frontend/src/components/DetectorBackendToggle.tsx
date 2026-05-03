import { useEffect, useState } from 'react';
import { apiUrl } from '../api/client';

interface BackendState {
  active: string;
  available: string[];
  pending: string | null;
  label: string;
}

const PRETTY: Record<string, string> = {
  rfdetr: 'RF-DETR',
  ultralytics: 'YOLO',
};

export function DetectorBackendToggle() {
  const [state, setState] = useState<BackendState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll the active backend every 2s — covers both our own switches and
  // the case where someone else (env var, another tab) flipped it.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(apiUrl('/api/tracker/backend'));
        if (!r.ok) throw new Error(String(r.status));
        const j = (await r.json()) as BackendState;
        if (alive) {
          setState(j);
          setError(null);
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

  const switchTo = async (name: string) => {
    if (!state || name === state.active || busy) return;
    setBusy(name);
    setError(null);
    try {
      const r = await fetch(apiUrl('/api/tracker/backend'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend: name }),
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`${r.status} ${txt}`);
      }
      const j = (await r.json()) as BackendState;
      setState(j);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (!state) {
    return (
      <div style={panelStyle}>
        <span style={labelStyle}>DETECTOR</span>
        <span style={{ ...pillStyle, opacity: 0.6 }}>loading…</span>
      </div>
    );
  }

  return (
    <div style={panelStyle}>
      <span style={labelStyle}>DETECTOR</span>
      {state.available.map((name) => {
        const active = state.active === name;
        const pending = state.pending === name;
        return (
          <button
            key={name}
            onClick={() => switchTo(name)}
            disabled={active || !!busy}
            style={{
              ...pillStyle,
              cursor: active ? 'default' : busy ? 'wait' : 'pointer',
              background: active ? '#22c55e' : 'transparent',
              color: active ? '#0a0e15' : '#e5e7eb',
              borderColor: active ? '#22c55e' : '#475569',
              fontWeight: active ? 700 : 500,
              opacity: pending ? 0.7 : 1,
            }}
            title={pending ? 'switching…' : `Switch to ${PRETTY[name] ?? name}`}
          >
            {PRETTY[name] ?? name}
            {pending ? ' …' : ''}
          </button>
        );
      })}
      <span style={{ ...labelStyle, marginLeft: 'auto', opacity: 0.7 }}>
        {state.label}
      </span>
      {error && (
        <span style={{ color: '#f87171', fontSize: 12, marginLeft: 8 }}>
          {error}
        </span>
      )}
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '6px 10px',
  marginBottom: 10,
  background: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 8,
};

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 0.6,
  color: '#94a3b8',
  textTransform: 'uppercase',
  fontWeight: 600,
};

const pillStyle: React.CSSProperties = {
  border: '1px solid',
  padding: '4px 12px',
  borderRadius: 999,
  fontSize: 12,
  letterSpacing: 0.4,
};
