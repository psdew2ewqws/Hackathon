import { useEffect, useRef, useState } from 'react';
import { apiUrl } from '../api/client';

type Approach = 'N' | 'S' | 'E' | 'W';
const APPROACHES: Approach[] = ['S', 'N', 'E', 'W'];

interface ApproachGeometry {
  approach_polygon: number[][];
  stop_line: [number, number][] | null;
  direction_of_travel: string;
}

interface StateResponse {
  approach_geometry?: Record<string, ApproachGeometry>;
}

const APPROACH_FILL: Record<string, string> = {
  S: 'rgba(102, 255, 136, 0.30)',
  N: 'rgba(255, 122, 122, 0.30)',
  E: 'rgba(245, 165, 60, 0.30)',
  W: 'rgba(74, 172, 203, 0.30)',
};
const APPROACH_STROKE: Record<string, string> = {
  S: '#66ff88',
  N: '#ff7a7a',
  E: '#f5a53c',
  W: '#4aaccb',
};

const VERTEX_R = 9;
const FRAME_W = 1920;
const FRAME_H = 1080;

interface EditableApproach {
  approach: Approach;
  polygon: number[][];
  stop_line: [number, number][] | null;
  direction_of_travel: string;
}

/**
 * Click-to-edit-vertex approach-zone editor that overlays the live MJPEG.
 * Hidden behind an "Edit approach zones" toggle on the Live page so it
 * only shows when the operator wants to redraw the outer geometry.
 *
 * Click a vertex to drag it. Right-click a vertex to delete. Click on
 * empty space to add a vertex (end of selected approach's polygon).
 * Stop-line endpoints are the first 2 polygon vertices by convention
 * (matches the existing wadi_saqra_zones.json schema).
 */
export function ApproachZoneEditor({ onClose }: { onClose: () => void }) {
  const [approaches, setApproaches] = useState<EditableApproach[]>([]);
  const [activeApproach, setActiveApproach] = useState<Approach>('S');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [snapshotKey, setSnapshotKey] = useState(0);

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const draggingVertex = useRef<{ approach: Approach; vIdx: number } | null>(null);
  const imgNaturalSize = useRef<{ w: number; h: number }>({ w: FRAME_W, h: FRAME_H });

  const loadCurrent = async () => {
    setBusy('loading');
    try {
      const r = await fetch(apiUrl('/api/lanes/state'));
      if (!r.ok) throw new Error(`/api/lanes/state ${r.status}`);
      const j = (await r.json()) as StateResponse;
      const out: EditableApproach[] = [];
      for (const ap of APPROACHES) {
        const g = j.approach_geometry?.[ap];
        if (!g) continue;
        out.push({
          approach: ap,
          polygon: g.approach_polygon.map(([x, y]) => [Math.round(x), Math.round(y)]),
          stop_line: g.stop_line ?? null,
          direction_of_travel: g.direction_of_travel || 'up',
        });
      }
      setApproaches(out);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => { void loadCurrent(); }, []);

  const screenToFrame = (clientX: number, clientY: number): [number, number] => {
    const wrap = wrapRef.current;
    if (!wrap) return [0, 0];
    const rect = wrap.getBoundingClientRect();
    const sx = (clientX - rect.left) / rect.width;
    const sy = (clientY - rect.top) / rect.height;
    return [
      Math.round(sx * imgNaturalSize.current.w),
      Math.round(sy * imgNaturalSize.current.h),
    ];
  };

  const findApproach = (a: Approach) => approaches.find((p) => p.approach === a);
  const updateApproach = (a: Approach, patch: Partial<EditableApproach>) => {
    setApproaches((cur) => cur.map((p) => (p.approach === a ? { ...p, ...patch } : p)));
  };

  const onCanvasMouseDown = (ev: React.MouseEvent) => {
    const ap = findApproach(activeApproach);
    if (!ap) return;
    const [fx, fy] = screenToFrame(ev.clientX, ev.clientY);
    if (ev.button === 2) {
      ev.preventDefault();
      const vIdx = nearestVertex(ap.polygon, fx, fy, 25);
      if (vIdx >= 0 && ap.polygon.length > 3) {
        updateApproach(activeApproach, {
          polygon: ap.polygon.filter((_, i) => i !== vIdx),
        });
      }
      return;
    }
    const vIdx = nearestVertex(ap.polygon, fx, fy, 22);
    if (vIdx >= 0) {
      draggingVertex.current = { approach: activeApproach, vIdx };
      return;
    }
    updateApproach(activeApproach, { polygon: [...ap.polygon, [fx, fy]] });
  };

  const onCanvasMouseMove = (ev: React.MouseEvent) => {
    const drag = draggingVertex.current;
    if (!drag) return;
    const [fx, fy] = screenToFrame(ev.clientX, ev.clientY);
    setApproaches((cur) =>
      cur.map((p) => {
        if (p.approach !== drag.approach) return p;
        const next = p.polygon.map((v, j) => (j === drag.vIdx ? [fx, fy] : v));
        // Stop_line tracks the first 2 polygon vertices by convention.
        const stopLine: [number, number][] | null =
          next.length >= 2 ? [next[0] as [number, number], next[1] as [number, number]] : p.stop_line;
        return { ...p, polygon: next, stop_line: stopLine };
      }),
    );
  };

  const onCanvasMouseUp = () => { draggingVertex.current = null; };

  // Re-render canvas when geometry changes.
  useEffect(() => {
    const cv = canvasRef.current;
    const wrap = wrapRef.current;
    const img = wrap?.querySelector('img') as HTMLImageElement | null;
    if (!cv || !wrap || !img) return;
    const draw = () => {
      const w = img.naturalWidth || FRAME_W;
      const h = img.naturalHeight || FRAME_H;
      imgNaturalSize.current = { w, h };
      cv.width = w; cv.height = h;
      const ctx = cv.getContext('2d');
      if (!ctx) return;
      ctx.clearRect(0, 0, w, h);
      for (const p of approaches) {
        const isActive = p.approach === activeApproach;
        const fill = APPROACH_FILL[p.approach] ?? 'rgba(255,255,255,0.2)';
        const stroke = APPROACH_STROKE[p.approach] ?? '#fff';
        ctx.beginPath();
        p.polygon.forEach(([x, y], i) => {
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        if (p.polygon.length >= 3) ctx.closePath();
        ctx.fillStyle = fill;
        if (p.polygon.length >= 3) ctx.fill();
        ctx.strokeStyle = stroke;
        ctx.lineWidth = isActive ? 5 : 3;
        ctx.stroke();
        // Stop line in yellow
        if (p.stop_line && p.stop_line.length >= 2) {
          ctx.beginPath();
          ctx.moveTo(p.stop_line[0][0], p.stop_line[0][1]);
          ctx.lineTo(p.stop_line[1][0], p.stop_line[1][1]);
          ctx.strokeStyle = '#facc15';
          ctx.lineWidth = 4;
          ctx.stroke();
        }
        // Vertex handles
        for (let i = 0; i < p.polygon.length; i++) {
          const [vx, vy] = p.polygon[i];
          ctx.beginPath();
          ctx.arc(vx, vy, isActive ? VERTEX_R : VERTEX_R - 2, 0, Math.PI * 2);
          ctx.fillStyle = isActive ? '#fff' : stroke;
          ctx.fill();
          ctx.strokeStyle = stroke;
          ctx.lineWidth = 2;
          ctx.stroke();
          // Index label so the operator knows v0+v1 are the stop-line endpoints
          if (isActive) {
            ctx.fillStyle = '#0a0e15';
            ctx.font = 'bold 12px system-ui';
            ctx.fillText(String(i), vx - 4, vy + 4);
          }
        }
        // Approach label
        const cx = p.polygon.reduce((a, [x]) => a + x, 0) / Math.max(p.polygon.length, 1);
        const cy = p.polygon.reduce((a, [, y]) => a + y, 0) / Math.max(p.polygon.length, 1);
        ctx.font = 'bold 36px system-ui';
        ctx.fillStyle = stroke;
        ctx.strokeStyle = '#0a0e15';
        ctx.lineWidth = 6;
        ctx.strokeText(p.approach, cx - 12, cy + 12);
        ctx.fillText(p.approach, cx - 12, cy + 12);
      }
    };
    if (img.complete) draw();
    else img.onload = draw;
  }, [approaches, activeApproach, snapshotKey]);

  const saveAll = async () => {
    setBusy('saving');
    setMsg(null); setError(null);
    try {
      const r = await fetch(apiUrl('/api/zones/calibrate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          zones: approaches.map((p) => ({
            approach: p.approach,
            polygon: p.polygon,
            stop_line: p.stop_line,
            direction_of_travel: p.direction_of_travel,
          })),
        }),
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`${r.status} ${txt}`);
      }
      const j = await r.json();
      setMsg(`saved ${j.approaches_written} approaches`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
      window.setTimeout(() => setMsg(null), 2500);
    }
  };

  return (
    <div style={{
      background: '#0f172a',
      border: '1px solid #1e293b',
      borderRadius: 8,
      padding: 10,
      marginBottom: 10,
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={labelStyle}>EDIT APPROACH ZONES</span>
        <select value={activeApproach}
          onChange={(e) => setActiveApproach(e.target.value as Approach)} style={selectStyle}>
          {APPROACHES.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <button onClick={saveAll} disabled={!!busy} style={btn('#fbbf24')}>
          {busy === 'saving' ? 'saving…' : 'Save approaches'}
        </button>
        <button onClick={loadCurrent} disabled={!!busy} style={btn('#475569')}>
          Reload
        </button>
        <button onClick={() => setSnapshotKey((k) => k + 1)} style={btn('#475569')}>
          Refresh snapshot
        </button>
        <button onClick={onClose} style={{ ...btn('#475569'), marginLeft: 'auto' }}>
          Close editor
        </button>
        {msg && <span style={{ color: '#4ade80', fontSize: 11 }}>{msg}</span>}
        {error && <span style={{ color: '#f87171', fontSize: 11 }}>{error}</span>}
      </div>
      <div style={{ fontSize: 11, opacity: 0.6 }}>
        Click empty space to add a vertex • drag a vertex to move • right-click to delete (min 3 vertices) •
        v0+v1 of each polygon define the stop line (yellow)
      </div>

      <div
        ref={wrapRef}
        style={{ position: 'relative', width: '100%', maxWidth: 960 }}
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
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', cursor: 'crosshair' }}
        />
      </div>
    </div>
  );
}

function nearestVertex(poly: number[][], fx: number, fy: number, threshold: number): number {
  let best = -1; let bestD = threshold;
  for (let i = 0; i < poly.length; i++) {
    const dx = poly[i][0] - fx;
    const dy = poly[i][1] - fy;
    const d = Math.sqrt(dx * dx + dy * dy);
    if (d <= bestD) { bestD = d; best = i; }
  }
  return best;
}

const labelStyle: React.CSSProperties = {
  fontSize: 11, letterSpacing: 0.6, color: '#94a3b8',
  textTransform: 'uppercase', fontWeight: 700,
};
const selectStyle: React.CSSProperties = {
  background: '#0b0f14', color: '#e6edf3', border: '1px solid #1e293b',
  borderRadius: 6, padding: '4px 8px', fontSize: 12,
};
function btn(bg: string): React.CSSProperties {
  return {
    background: bg, color: '#0a0e15', border: 'none', borderRadius: 6,
    padding: '4px 12px', fontWeight: 600, cursor: 'pointer', fontSize: 12,
  };
}
