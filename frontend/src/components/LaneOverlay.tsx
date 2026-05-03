import { useEffect, useState } from 'react';
import { apiUrl } from '../api/client';

interface LaneShape {
  lane_id: string;
  lane_idx: number;
  lane_type: string;
  polygon: number[][];
  centerline: number[][];
}

interface StateResponse {
  saved_lanes: Record<string, LaneShape[]>;
}

const LANE_FILL: Record<string, string> = {
  left: 'rgba(96, 165, 250, 0.35)',
  through: 'rgba(74, 222, 128, 0.35)',
  right: 'rgba(251, 191, 36, 0.35)',
  shared: 'rgba(148, 163, 184, 0.35)',
};

const LANE_STROKE: Record<string, string> = {
  left: '#60a5fa',
  through: '#4ade80',
  right: '#fbbf24',
  shared: '#94a3b8',
};

const FRAME_W = 1920;
const FRAME_H = 1080;

/**
 * Renders saved per-lane polygons as a translucent SVG overlay on top of
 * an MJPEG <img>. Place inside a position:relative container that holds
 * the <img>; this component absolutely-positions itself to fill it.
 */
export function LaneOverlay() {
  const [saved, setSaved] = useState<Record<string, LaneShape[]>>({});

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(apiUrl('/api/lanes/state'));
        if (!r.ok) return;
        const j = (await r.json()) as StateResponse;
        if (alive) setSaved(j.saved_lanes ?? {});
      } catch {
        /* swallow — overlay is opt-in nice-to-have */
      }
    };
    tick();
    const id = window.setInterval(tick, 5000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const all: LaneShape[] = Object.values(saved).flat();
  if (all.length === 0) return null;

  return (
    <svg
      viewBox={`0 0 ${FRAME_W} ${FRAME_H}`}
      preserveAspectRatio="xMidYMid slice"
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
      }}
    >
      {all.map((ln) => {
        const points = ln.polygon.map(([x, y]) => `${x},${y}`).join(' ');
        const fill = LANE_FILL[ln.lane_type] ?? LANE_FILL.shared;
        const stroke = LANE_STROKE[ln.lane_type] ?? LANE_STROKE.shared;
        const cl = ln.centerline;
        const mid = cl[Math.floor(cl.length / 2)] ?? ln.polygon[0];
        return (
          <g key={ln.lane_id}>
            <polygon points={points} fill={fill} stroke={stroke} strokeWidth={3} />
            <text
              x={mid[0]}
              y={mid[1]}
              fill="#0a0e15"
              fontSize={22}
              fontWeight={700}
              textAnchor="middle"
              style={{ paintOrder: 'stroke', stroke: '#ffffff', strokeWidth: 4 }}
            >
              {ln.lane_id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
