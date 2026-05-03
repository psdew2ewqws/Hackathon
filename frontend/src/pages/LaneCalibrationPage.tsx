import { useEffect, useMemo, useRef, useState } from 'react';
import { apiUrl } from '../api/client';

type LaneType = 'left' | 'through' | 'right' | 'shared';
type Approach = 'N' | 'S' | 'E' | 'W';

interface LaneSpec {
  lane_id: string;
  lane_idx: number;
  lane_type: LaneType;
  polygon: number[][];     // [[x, y], ...] integer pixels
  centerline: number[][];
}

interface ProposedResponse {
  trajectories_seen: number;
  proposed: Record<string, LaneSpec[]>;
  warning?: string;
}

interface StateResponse {
  saved_lanes: Record<string, LaneSpec[]>;
  live: Record<string, Record<string, {
    in_zone: number;
    in_zone_pce: number;
    crossings_total: number;
    lane_type: string;
  }>>;
}

const LANE_FILL: Record<string, string> = {
  left: 'rgba(96, 165, 250, 0.40)',
  through: 'rgba(74, 222, 128, 0.40)',
  right: 'rgba(251, 191, 36, 0.40)',
  shared: 'rgba(148, 163, 184, 0.40)',
};
const LANE_STROKE: Record<string, string> = {
  left: '#60a5fa',
  through: '#4ade80',
  right: '#fbbf24',
  shared: '#94a3b8',
};
const APPROACHES: Approach[] = ['N', 'S', 'E', 'W'];

const FRAME_W = 1920;
const FRAME_H = 1080;
const VERTEX_RADIUS = 8;

interface EditableLane {
  approach: Approach;
  lane_id: string;
  lane_idx: number;
  lane_type: LaneType;
  polygon: number[][];
}

export function LaneCalibrationPage() {
  const [lanes, setLanes] = useState<EditableLane[]>([]);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [activeApproach, setActiveApproach] = useState<Approach>('N');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [snapshotKey, setSnapshotKey] = useState(0);
  const [proposed, setProposed] = useState<ProposedResponse | null>(null);
  const [showProposedAsRef, setShowProposedAsRef] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const draggingVertex = useRef<{ laneIdx: number; vIdx: number } | null>(null);
  const imgNaturalSize = useRef<{ w: number; h: number }>({ w: FRAME_W, h: FRAME_H });

  // Load saved lanes once on mount
  useEffect(() => {
    void loadSaved();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadSaved = async () => {
    setBusy('loading');
    try {
      const r = await fetch(apiUrl('/api/lanes/state'));
      if (!r.ok) throw new Error(`/api/lanes/state ${r.status}`);
      const j = (await r.json()) as StateResponse;
      const out: EditableLane[] = [];
      for (const [approach, list] of Object.entries(j.saved_lanes)) {
        for (const ln of list) {
          out.push({
            approach: approach as Approach,
            lane_id: ln.lane_id,
            lane_idx: ln.lane_idx,
            lane_type: (ln.lane_type as LaneType) || 'shared',
            polygon: ln.polygon.map(([x, y]) => [Math.round(x), Math.round(y)]),
          });
        }
      }
      setLanes(out);
      setSelectedIdx(out.length > 0 ? 0 : null);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const induceProposal = async () => {
    setBusy('inducing');
    setError(null);
    try {
      const r = await fetch(apiUrl('/api/lanes/proposed'));
      if (!r.ok) throw new Error(`/api/lanes/proposed ${r.status}`);
      const j = (await r.json()) as ProposedResponse;
      setProposed(j);
      setShowProposedAsRef(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const adoptProposed = () => {
    if (!proposed?.proposed) return;
    const out: EditableLane[] = [];
    for (const [approach, list] of Object.entries(proposed.proposed)) {
      for (const ln of list) {
        out.push({
          approach: approach as Approach,
          lane_id: ln.lane_id,
          lane_idx: ln.lane_idx,
          lane_type: (ln.lane_type as LaneType) || 'shared',
          polygon: ln.polygon.map(([x, y]) => [Math.round(x), Math.round(y)]),
        });
      }
    }
    setLanes(out);
    setSelectedIdx(out.length > 0 ? 0 : null);
    setShowProposedAsRef(false);
  };

  const saveAll = async () => {
    setBusy('saving');
    setError(null);
    try {
      const grouped: Record<string, LaneSpec[]> = {};
      // Re-index lanes per approach so lane_id is contiguous (S-1, S-2, ...).
      const byApproach: Record<string, EditableLane[]> = {};
      for (const ln of lanes) {
        if (ln.polygon.length < 3) continue;
        (byApproach[ln.approach] ||= []).push(ln);
      }
      for (const [approach, list] of Object.entries(byApproach)) {
        list.sort((a, b) => a.lane_idx - b.lane_idx);
        grouped[approach] = list.map((ln, i) => ({
          lane_id: `${approach}-${i + 1}`,
          lane_idx: i,
          lane_type: ln.lane_type,
          polygon: ln.polygon,
          centerline: centerlineFromPolygon(ln.polygon),
        }));
      }
      const r = await fetch(apiUrl('/api/lanes/calibrate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lanes: grouped }),
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`${r.status} ${txt}`);
      }
      await loadSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const addLane = () => {
    const nextIdx = lanes.filter((l) => l.approach === activeApproach).length;
    const newLane: EditableLane = {
      approach: activeApproach,
      lane_id: `${activeApproach}-${nextIdx + 1}`,
      lane_idx: nextIdx,
      lane_type: 'through',
      polygon: [],
    };
    setLanes((cur) => [...cur, newLane]);
    setSelectedIdx(lanes.length);
  };

  const deleteLane = (idx: number) => {
    setLanes((cur) => cur.filter((_, i) => i !== idx));
    setSelectedIdx(null);
  };

  const setLaneType = (idx: number, type: LaneType) => {
    setLanes((cur) => cur.map((l, i) => (i === idx ? { ...l, lane_type: type } : l)));
  };

  const setLaneApproach = (idx: number, approach: Approach) => {
    setLanes((cur) => cur.map((l, i) => (i === idx ? { ...l, approach } : l)));
  };

  // ---------------- canvas event handling ----------------

  const screenToFrame = (clientX: number, clientY: number): [number, number] => {
    const wrap = wrapRef.current;
    if (!wrap) return [0, 0];
    const rect = wrap.getBoundingClientRect();
    const sx = (clientX - rect.left) / rect.width;
    const sy = (clientY - rect.top) / rect.height;
    return [Math.round(sx * imgNaturalSize.current.w), Math.round(sy * imgNaturalSize.current.h)];
  };

  const onCanvasMouseDown = (ev: React.MouseEvent) => {
    if (selectedIdx === null) return;
    const [fx, fy] = screenToFrame(ev.clientX, ev.clientY);
    const lane = lanes[selectedIdx];
    // Right click → delete nearest vertex on selected lane (if close).
    if (ev.button === 2) {
      ev.preventDefault();
      const vIdx = nearestVertex(lane.polygon, fx, fy, 25);
      if (vIdx >= 0) {
        const next = lane.polygon.filter((_, i) => i !== vIdx);
        updateLane(selectedIdx, { polygon: next });
      }
      return;
    }
    // Left click on a vertex → start dragging.
    const vIdx = nearestVertex(lane.polygon, fx, fy, 20);
    if (vIdx >= 0) {
      draggingVertex.current = { laneIdx: selectedIdx, vIdx };
      return;
    }
    // Otherwise append a new vertex.
    updateLane(selectedIdx, { polygon: [...lane.polygon, [fx, fy]] });
  };

  const onCanvasMouseMove = (ev: React.MouseEvent) => {
    const drag = draggingVertex.current;
    if (!drag) return;
    const [fx, fy] = screenToFrame(ev.clientX, ev.clientY);
    setLanes((cur) =>
      cur.map((l, i) => {
        if (i !== drag.laneIdx) return l;
        const next = l.polygon.map((p, j) => (j === drag.vIdx ? [fx, fy] : p));
        return { ...l, polygon: next };
      }),
    );
  };

  const onCanvasMouseUp = () => {
    draggingVertex.current = null;
  };

  const updateLane = (idx: number, patch: Partial<EditableLane>) => {
    setLanes((cur) => cur.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  };

  // ---------------- drawing ----------------

  const proposedLanesFlat = useMemo(() => {
    if (!proposed?.proposed || !showProposedAsRef) return [];
    const out: { approach: string; ln: LaneSpec }[] = [];
    for (const [a, list] of Object.entries(proposed.proposed)) {
      for (const ln of list) out.push({ approach: a, ln });
    }
    return out;
  }, [proposed, showProposedAsRef]);

  useEffect(() => {
    const cv = canvasRef.current;
    const wrap = wrapRef.current;
    const img = wrap?.querySelector('img') as HTMLImageElement | null;
    if (!cv || !wrap || !img) return;
    const draw = () => {
      const w = img.naturalWidth || FRAME_W;
      const h = img.naturalHeight || FRAME_H;
      imgNaturalSize.current = { w, h };
      cv.width = w;
      cv.height = h;
      const ctx = cv.getContext('2d');
      if (!ctx) return;
      ctx.clearRect(0, 0, w, h);

      // Proposed-as-reference (dashed)
      if (showProposedAsRef) {
        for (const { ln } of proposedLanesFlat) {
          ctx.beginPath();
          ln.polygon.forEach(([x, y], i) => {
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          });
          ctx.closePath();
          ctx.strokeStyle = LANE_STROKE[ln.lane_type] ?? LANE_STROKE.shared;
          ctx.lineWidth = 2;
          ctx.setLineDash([10, 6]);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }

      // Editable lanes
      lanes.forEach((lane, idx) => {
        if (lane.polygon.length < 1) return;
        const isSel = selectedIdx === idx;
        ctx.beginPath();
        lane.polygon.forEach(([x, y], i) => {
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        if (lane.polygon.length >= 3) ctx.closePath();
        ctx.fillStyle = LANE_FILL[lane.lane_type] ?? LANE_FILL.shared;
        if (lane.polygon.length >= 3) ctx.fill();
        ctx.strokeStyle = LANE_STROKE[lane.lane_type] ?? LANE_STROKE.shared;
        ctx.lineWidth = isSel ? 5 : 3;
        ctx.stroke();
        // Vertex handles
        for (const [vx, vy] of lane.polygon) {
          ctx.beginPath();
          ctx.arc(vx, vy, isSel ? VERTEX_RADIUS : VERTEX_RADIUS - 2, 0, Math.PI * 2);
          ctx.fillStyle = isSel ? '#fff' : LANE_STROKE[lane.lane_type];
          ctx.fill();
          ctx.strokeStyle = LANE_STROKE[lane.lane_type];
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        // Label at first vertex
        const [lx, ly] = lane.polygon[0];
        const label = `${lane.lane_id} ${lane.lane_type}`;
        ctx.font = 'bold 22px system-ui, sans-serif';
        const m = ctx.measureText(label);
        ctx.fillStyle = '#0a0e15';
        ctx.fillRect(lx + 10, ly - 30, m.width + 14, 28);
        ctx.fillStyle = '#fff';
        ctx.fillText(label, lx + 17, ly - 10);
      });
    };
    if (img.complete) draw();
    else img.onload = draw;
  }, [lanes, selectedIdx, snapshotKey, proposedLanesFlat, showProposedAsRef]);

  // ---------------- UI ----------------

  return (
    <div style={{ padding: 14, color: '#e6edf3', display: 'flex', flexDirection: 'column', gap: 10 }}>
      <h1 style={{ fontSize: 22, margin: 0 }}>Lane calibration (manual)</h1>
      <p style={{ opacity: 0.7, margin: 0, fontSize: 13 }}>
        Click on the snapshot to add polygon vertices. Drag a vertex to move it.
        Right-click a vertex to delete it. A polygon needs ≥3 vertices to fill.
        Use <em>Re-induce</em> to overlay the algorithm's proposal as a dashed reference,
        then <em>Adopt proposal</em> to copy it into editable shape, or just draw your own.
      </p>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={activeApproach} onChange={(e) => setActiveApproach(e.target.value as Approach)}
          style={selectStyle}>
          {APPROACHES.map((a) => <option key={a} value={a}>Add to {a}</option>)}
        </select>
        <button onClick={addLane} disabled={!!busy} style={btn('#22c55e')}>+ New lane</button>
        <button onClick={induceProposal} disabled={!!busy} style={btn('#a78bfa')}>
          {busy === 'inducing' ? 'inducing…' : 'Re-induce reference'}
        </button>
        <button onClick={adoptProposed} disabled={!proposed?.proposed || !!busy} style={btn('#3b82f6')}>
          Adopt proposal
        </button>
        <button onClick={() => setShowProposedAsRef((v) => !v)} disabled={!proposed?.proposed}
          style={btn('#475569')}>
          ref: {showProposedAsRef ? 'shown' : 'hidden'}
        </button>
        <button onClick={loadSaved} disabled={!!busy} style={btn('#475569')}>
          Reload saved
        </button>
        <button onClick={() => setSnapshotKey((k) => k + 1)} style={btn('#475569')}>
          Refresh snapshot
        </button>
        <button onClick={saveAll} disabled={!!busy || lanes.length === 0} style={btn('#fbbf24')}>
          {busy === 'saving' ? 'saving…' : `Save all (${lanes.length})`}
        </button>
      </div>

      {error && (
        <div style={{ background: '#7f1d1d', padding: 8, borderRadius: 6, fontSize: 13 }}>
          {error}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 3fr) 280px', gap: 12 }}>
        <div
          ref={wrapRef}
          style={{ position: 'relative', width: '100%' }}
          onMouseMove={onCanvasMouseMove}
          onMouseUp={onCanvasMouseUp}
          onContextMenu={(e) => e.preventDefault()}
        >
          <img
            src={apiUrl(`/mjpeg?nocache=${snapshotKey}`)}
            alt="snapshot"
            style={{ width: '100%', display: 'block', borderRadius: 8 }}
            crossOrigin="anonymous"
          />
          <canvas
            ref={canvasRef}
            onMouseDown={onCanvasMouseDown}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              cursor: selectedIdx === null ? 'default' : 'crosshair',
            }}
          />
        </div>

        <aside style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <h2 style={{ fontSize: 14, margin: 0, opacity: 0.8, letterSpacing: 0.4, textTransform: 'uppercase' }}>
            Lanes ({lanes.length})
          </h2>
          {lanes.length === 0 && (
            <div style={{ opacity: 0.6, fontSize: 12 }}>
              No lanes yet. Pick an approach above and click <em>+ New lane</em>, then click on the image
              to drop vertices.
            </div>
          )}
          {lanes.map((ln, idx) => (
            <div
              key={idx}
              onClick={() => setSelectedIdx(idx)}
              style={{
                background: selectedIdx === idx ? '#1e293b' : '#0f172a',
                border: `1px solid ${selectedIdx === idx ? LANE_STROKE[ln.lane_type] : '#1e293b'}`,
                borderRadius: 8,
                padding: 8,
                cursor: 'pointer',
                fontSize: 12,
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong style={{ fontSize: 13 }}>{ln.lane_id}</strong>
                <span style={{ opacity: 0.6 }}>{ln.polygon.length} pts</span>
              </div>
              <div style={{ display: 'flex', gap: 4 }}>
                <select value={ln.approach}
                  onChange={(e) => setLaneApproach(idx, e.target.value as Approach)}
                  onClick={(e) => e.stopPropagation()}
                  style={{ ...selectStyle, fontSize: 12, padding: 2, flex: 1 }}>
                  {APPROACHES.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
                <select value={ln.lane_type}
                  onChange={(e) => setLaneType(idx, e.target.value as LaneType)}
                  onClick={(e) => e.stopPropagation()}
                  style={{ ...selectStyle, fontSize: 12, padding: 2, flex: 1 }}>
                  <option value="left">left</option>
                  <option value="through">through</option>
                  <option value="right">right</option>
                  <option value="shared">shared</option>
                </select>
                <button
                  onClick={(e) => { e.stopPropagation(); deleteLane(idx); }}
                  style={{ ...btn('#ef4444'), padding: '2px 8px', fontSize: 11 }}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </aside>
      </div>
    </div>
  );
}

// ---------------- helpers ----------------

function nearestVertex(poly: number[][], fx: number, fy: number, threshold: number): number {
  let best = -1;
  let bestD = threshold;
  for (let i = 0; i < poly.length; i++) {
    const dx = poly[i][0] - fx;
    const dy = poly[i][1] - fy;
    const d = Math.sqrt(dx * dx + dy * dy);
    if (d <= bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

function centerlineFromPolygon(poly: number[][]): number[][] {
  // Half-perimeter centerline: walk around the polygon, take the midpoint
  // between vertex i and vertex (n - 1 - i) — works well for "ribbon" lane
  // polygons that look like {left edge + reversed right edge}.
  const n = poly.length;
  if (n < 4) {
    // Just give a single midpoint if we can't infer left/right edges.
    const cx = poly.reduce((a, [x]) => a + x, 0) / n;
    const cy = poly.reduce((a, [, y]) => a + y, 0) / n;
    return [[cx, cy]];
  }
  const half = Math.floor(n / 2);
  const out: number[][] = [];
  for (let i = 0; i < half; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[n - 1 - i];
    out.push([(x1 + x2) / 2, (y1 + y2) / 2]);
  }
  return out;
}

const btn = (bg: string): React.CSSProperties => ({
  background: bg,
  color: '#0a0e15',
  border: 'none',
  borderRadius: 6,
  padding: '6px 12px',
  fontWeight: 600,
  cursor: 'pointer',
  fontSize: 12,
});

const selectStyle: React.CSSProperties = {
  background: '#0f172a',
  color: '#e6edf3',
  border: '1px solid #1e293b',
  borderRadius: 6,
  padding: '6px 10px',
  fontSize: 12,
};
