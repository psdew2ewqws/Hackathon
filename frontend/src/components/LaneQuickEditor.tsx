import { useEffect, useState } from 'react';
import { apiUrl } from '../api/client';
import {
  centerlineFromPolygon,
  equalDivideApproach,
  laneTypeFor,
} from '../lib/laneGeometry';

type Approach = 'N' | 'S' | 'E' | 'W';

interface LaneShape {
  lane_id: string;
  lane_idx: number;
  lane_type: string;
  polygon: number[][];
  centerline: number[][];
}

interface ApproachGeometry {
  approach_polygon: number[][];
  stop_line: [number, number][] | null;
  direction_of_travel: string;
}

interface StateResponse {
  saved_lanes: Record<string, LaneShape[]>;
  approach_geometry?: Record<string, ApproachGeometry>;
}

const APPROACHES: Approach[] = ['S', 'N', 'E', 'W'];

/**
 * Inline lane editor that lives directly above the live MJPEG. Handles the
 * 90% case: "wipe the auto-induced lanes for this approach and replace
 * with N perspective-correct strips." For full vertex-by-vertex editing,
 * the dedicated `/lanes` page still exists.
 */
export function LaneQuickEditor() {
  const [state, setState] = useState<StateResponse | null>(null);
  const [activeApproach, setActiveApproach] = useState<Approach>('S');
  const [n, setN] = useState<number>(3);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const r = await fetch(apiUrl('/api/lanes/state'));
      if (!r.ok) throw new Error(`/api/lanes/state ${r.status}`);
      setState((await r.json()) as StateResponse);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    void refresh();
    const id = window.setInterval(refresh, 5000);
    return () => window.clearInterval(id);
  }, []);

  const postLanes = async (next: Record<string, LaneShape[]>) => {
    setBusy('saving');
    setMsg(null);
    setError(null);
    try {
      const r = await fetch(apiUrl('/api/lanes/calibrate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lanes: next }),
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`${r.status} ${txt}`);
      }
      const total = Object.values(next).reduce((a, l) => a + l.length, 0);
      setMsg(`saved ${total} lane${total === 1 ? '' : 's'}`);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
      window.setTimeout(() => setMsg(null), 2500);
    }
  };

  const divideAndSave = async () => {
    if (!state?.approach_geometry) return;
    const geom = state.approach_geometry[activeApproach];
    if (!geom?.stop_line) {
      setError(`No geometry for ${activeApproach}`);
      return;
    }
    const strips = equalDivideApproach(geom.approach_polygon, geom.stop_line, n);
    if (strips.length === 0) {
      setError(`Could not divide ${activeApproach}`);
      return;
    }
    // Replace lanes for this approach; keep others as-is.
    const next: Record<string, LaneShape[]> = {};
    for (const [ap, lanes] of Object.entries(state.saved_lanes || {})) {
      if (ap !== activeApproach) next[ap] = lanes;
    }
    next[activeApproach] = strips.map((poly, i) => ({
      lane_id: `${activeApproach}-${i + 1}`,
      lane_idx: i,
      lane_type: laneTypeFor(i, n),
      polygon: poly,
      centerline: centerlineFromPolygon(poly),
    }));
    await postLanes(next);
  };

  const clearApproach = async () => {
    if (!state) return;
    const next: Record<string, LaneShape[]> = {};
    for (const [ap, lanes] of Object.entries(state.saved_lanes || {})) {
      if (ap !== activeApproach) next[ap] = lanes;
    }
    next[activeApproach] = [];
    await postLanes(next);
  };

  const clearAll = async () => {
    if (!window.confirm('Clear all lanes on every approach?')) return;
    // Server treats an absent approach as "leave it alone" — to actually
    // wipe everything we must send each approach explicitly with [].
    const next: Record<string, LaneShape[]> = {};
    for (const ap of APPROACHES) next[ap] = [];
    await postLanes(next);
  };

  const savedCounts: Record<string, number> = {};
  for (const ap of APPROACHES) {
    savedCounts[ap] = (state?.saved_lanes?.[ap] ?? []).length;
  }
  const totalSaved = Object.values(savedCounts).reduce((a, b) => a + b, 0);

  return (
    <div style={panelStyle}>
      <span style={labelStyle}>LANES</span>
      <select
        value={activeApproach}
        onChange={(e) => setActiveApproach(e.target.value as Approach)}
        style={selectStyle}
      >
        {APPROACHES.map((a) => (
          <option key={a} value={a}>
            {a} ({savedCounts[a]})
          </option>
        ))}
      </select>
      <span style={subLabelStyle}>N</span>
      <input
        type="number"
        min={1}
        max={8}
        value={n}
        onChange={(e) => setN(Math.max(1, Math.min(8, parseInt(e.target.value) || 1)))}
        style={{ ...selectStyle, width: 56 }}
      />
      <button
        onClick={divideAndSave}
        disabled={!!busy || !state?.approach_geometry?.[activeApproach]}
        style={btn('#22c55e')}
        title={`Divide ${activeApproach} into ${n} perspective-correct strips and save`}
      >
        {busy === 'saving' ? 'saving…' : `Divide ${activeApproach} into ${n}`}
      </button>
      <button
        onClick={clearApproach}
        disabled={!!busy || savedCounts[activeApproach] === 0}
        style={btn('#475569')}
        title={`Remove all lanes from ${activeApproach}`}
      >
        Clear {activeApproach}
      </button>
      <button
        onClick={clearAll}
        disabled={!!busy || totalSaved === 0}
        style={{ ...btn('#7f1d1d'), color: '#fecaca' }}
        title="Wipe all lanes on every approach"
      >
        Clear all
      </button>
      <span style={{ marginLeft: 'auto', fontSize: 11, opacity: 0.7 }}>
        Total saved: {totalSaved} · refreshes every 5s
      </span>
      {msg && <span style={{ color: '#4ade80', fontSize: 11 }}>{msg}</span>}
      {error && <span style={{ color: '#f87171', fontSize: 11 }}>{error}</span>}
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
  flexWrap: 'wrap',
};

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 0.6,
  color: '#94a3b8',
  textTransform: 'uppercase',
  fontWeight: 700,
};

const subLabelStyle: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 0.4,
  color: '#94a3b8',
  textTransform: 'uppercase',
  fontWeight: 600,
};

const selectStyle: React.CSSProperties = {
  background: '#0b0f14',
  color: '#e6edf3',
  border: '1px solid #1e293b',
  borderRadius: 6,
  padding: '4px 8px',
  fontSize: 12,
};

function btn(bg: string): React.CSSProperties {
  return {
    background: bg,
    color: '#0a0e15',
    border: 'none',
    borderRadius: 6,
    padding: '4px 12px',
    fontWeight: 600,
    cursor: 'pointer',
    fontSize: 12,
  };
}
