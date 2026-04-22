/**
 * Tiny SVG chart primitives — pure React, no charting library. Each chart
 * owns its own sizing + ticks + tooltip. Deliberately minimal: the goal is
 * legibility on a dark ops dashboard, not feature parity with Recharts.
 */

import { useState } from 'react';

// ── Shared palette ───────────────────────────────────────────────
export const APPROACH_COLOR: Record<'N' | 'S' | 'E' | 'W', string> = {
  N: '#6FA8D6',
  S: '#D68F6B',
  E: '#7FA889',
  W: '#C583C5',
};

export const APPROACHES: Array<'N' | 'S' | 'E' | 'W'> = ['N', 'S', 'E', 'W'];

interface ChartBox {
  width: number;
  height: number;
  pad: { top: number; right: number; bottom: number; left: number };
}

function makeBox(width = 820, height = 240): ChartBox {
  return { width, height, pad: { top: 14, right: 20, bottom: 32, left: 44 } };
}

// ═══════════════════════════════════════════════════════════════════
// Multi-series line chart
// ═══════════════════════════════════════════════════════════════════

interface LineSeries {
  key: string;
  color: string;
  values: number[];
  label?: string;
}

interface LineChartProps {
  series: LineSeries[];
  xLabels: string[];
  yLabel?: string;
  width?: number;
  height?: number;
  xEvery?: number; // show tick every N labels
}

export function LineChart({
  series, xLabels, yLabel, width = 820, height = 240, xEvery,
}: LineChartProps) {
  const box = makeBox(width, height);
  const { pad } = box;
  const plotW = box.width - pad.left - pad.right;
  const plotH = box.height - pad.top - pad.bottom;
  const [hover, setHover] = useState<number | null>(null);

  const nPoints = xLabels.length || 1;
  const maxY = Math.max(
    1,
    ...series.flatMap((s) => s.values),
  );
  // Round max up to a nice tick
  const tickBase = Math.pow(10, Math.floor(Math.log10(Math.max(1, maxY))));
  const niceMax = Math.ceil(maxY / tickBase) * tickBase;
  const yTicks = 4;

  const xOf = (i: number) =>
    pad.left + (nPoints === 1 ? plotW / 2 : (i * plotW) / (nPoints - 1));
  const yOf = (v: number) => pad.top + plotH - (v / niceMax) * plotH;

  const xStep = xEvery ?? Math.max(1, Math.floor(nPoints / 8));

  return (
    <svg viewBox={`0 0 ${box.width} ${box.height}`}
         style={{ width: '100%', height: 'auto', maxWidth: box.width }}>
      {/* Y-axis grid + labels */}
      {Array.from({ length: yTicks + 1 }, (_, i) => {
        const v = (niceMax / yTicks) * i;
        const y = yOf(v);
        return (
          <g key={i}>
            <line x1={pad.left} x2={box.width - pad.right} y1={y} y2={y}
                  stroke="var(--border-soft)" strokeDasharray="2 4" />
            <text x={pad.left - 6} y={y + 3} textAnchor="end"
                  fontSize="10" fill="var(--fg-faint)" fontFamily="var(--mono)">
              {Math.round(v)}
            </text>
          </g>
        );
      })}

      {/* Y-axis label */}
      {yLabel && (
        <text x={pad.left - 32} y={pad.top + plotH / 2}
              fontSize="10" fill="var(--fg-faint)" fontFamily="var(--mono)"
              transform={`rotate(-90 ${pad.left - 32} ${pad.top + plotH / 2})`}
              textAnchor="middle">
          {yLabel}
        </text>
      )}

      {/* X tick labels */}
      {xLabels.map((lab, i) =>
        i % xStep === 0 || i === xLabels.length - 1 ? (
          <text key={i} x={xOf(i)} y={box.height - pad.bottom + 14}
                fontSize="10" fill="var(--fg-faint)"
                fontFamily="var(--mono)" textAnchor="middle">
            {lab}
          </text>
        ) : null,
      )}

      {/* Lines */}
      {series.map((s) => {
        const d = s.values
          .map((v, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i)} ${yOf(v)}`)
          .join(' ');
        return (
          <g key={s.key}>
            <path d={d} fill="none" stroke={s.color} strokeWidth={1.6}
                  strokeLinejoin="round" strokeLinecap="round" />
            {s.values.map((v, i) => (
              <circle key={i} cx={xOf(i)} cy={yOf(v)} r={2}
                      fill={s.color} opacity={0.9} />
            ))}
          </g>
        );
      })}

      {/* Hover column */}
      {xLabels.map((_, i) => (
        <rect key={i}
              x={xOf(i) - (plotW / Math.max(1, nPoints - 1)) / 2}
              y={pad.top}
              width={plotW / Math.max(1, nPoints - 1)}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)} />
      ))}

      {hover !== null && (
        <g>
          <line x1={xOf(hover)} x2={xOf(hover)} y1={pad.top}
                y2={box.height - pad.bottom}
                stroke="var(--fg-mute)" strokeDasharray="2 3" />
          <rect x={xOf(hover) + 8} y={pad.top}
                width={130} height={16 + series.length * 14} rx={4}
                fill="var(--surface-2)" stroke="var(--border)" />
          <text x={xOf(hover) + 16} y={pad.top + 14}
                fontSize="10" fill="var(--fg)"
                fontFamily="var(--mono)" fontWeight="500">
            {xLabels[hover]}
          </text>
          {series.map((s, j) => (
            <g key={s.key}>
              <rect x={xOf(hover) + 16} y={pad.top + 22 + j * 14}
                    width={7} height={7} fill={s.color} />
              <text x={xOf(hover) + 28} y={pad.top + 28 + j * 14}
                    fontSize="10" fill="var(--fg-dim)"
                    fontFamily="var(--mono)">
                {s.label ?? s.key}: <tspan fill="var(--fg)" fontWeight="500">
                  {s.values[hover]}
                </tspan>
              </text>
            </g>
          ))}
        </g>
      )}
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Heatmap grid (approach × time-slot)
// ═══════════════════════════════════════════════════════════════════

interface HeatmapCell {
  approach: 'N' | 'S' | 'E' | 'W';
  slotIdx: number;
  label: string;   // congestion tag: free/light/heavy/jam/unknown
  value: number | null;
  hhmm: string;
}

interface HeatmapProps {
  cells: HeatmapCell[];
  slotLabels: string[];   // x-axis labels (48 slots = every 30 min)
  width?: number;
  height?: number;
}

const LABEL_COLOR: Record<string, string> = {
  free: '#7FA889',
  light: '#E8B464',
  heavy: '#D68F6B',
  jam: '#B85450',
  unknown: '#2A2D35',
};

export function Heatmap({
  cells, slotLabels, width = 820, height = 170,
}: HeatmapProps) {
  const pad = { top: 12, right: 20, bottom: 28, left: 28 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const nCols = slotLabels.length || 1;
  const nRows = 4;
  const cw = plotW / nCols;
  const ch = plotH / nRows;
  const [hover, setHover] = useState<HeatmapCell | null>(null);

  return (
    <svg viewBox={`0 0 ${width} ${height}`}
         style={{ width: '100%', height: 'auto', maxWidth: width }}>
      {/* Approach labels */}
      {APPROACHES.map((a, i) => (
        <text key={a} x={pad.left - 6} y={pad.top + i * ch + ch / 2 + 4}
              fontSize="10" fill="var(--fg-dim)"
              fontFamily="var(--mono)" textAnchor="end" fontWeight="600">
          {a}
        </text>
      ))}

      {/* Cells */}
      {cells.map((c) => {
        const rowIdx = APPROACHES.indexOf(c.approach);
        if (rowIdx < 0) return null;
        const x = pad.left + c.slotIdx * cw;
        const y = pad.top + rowIdx * ch;
        return (
          <rect key={`${c.approach}-${c.slotIdx}`}
                x={x} y={y} width={Math.max(1, cw - 1)} height={ch - 1}
                fill={LABEL_COLOR[c.label] ?? LABEL_COLOR.unknown}
                opacity={c.label === 'unknown' ? 0.5 : 0.82}
                onMouseEnter={() => setHover(c)}
                onMouseLeave={() => setHover(null)} />
        );
      })}

      {/* Slot labels — every 4 slots (2h) */}
      {slotLabels.map((lab, i) =>
        i % 4 === 0 ? (
          <text key={i}
                x={pad.left + i * cw + cw / 2}
                y={height - pad.bottom + 14}
                fontSize="9" fill="var(--fg-faint)"
                fontFamily="var(--mono)" textAnchor="middle">
            {lab}
          </text>
        ) : null,
      )}

      {/* Hover tooltip */}
      {hover && (
        <g>
          <rect x={pad.left + hover.slotIdx * cw - 50}
                y={pad.top + APPROACHES.indexOf(hover.approach) * ch + ch + 4}
                width={170} height={42} rx={4}
                fill="var(--surface-2)" stroke="var(--border)" />
          <text x={pad.left + hover.slotIdx * cw - 42}
                y={pad.top + APPROACHES.indexOf(hover.approach) * ch + ch + 20}
                fontSize="10" fill="var(--fg)"
                fontFamily="var(--mono)" fontWeight="600">
            {hover.approach} @ {hover.hhmm}
          </text>
          <text x={pad.left + hover.slotIdx * cw - 42}
                y={pad.top + APPROACHES.indexOf(hover.approach) * ch + ch + 36}
                fontSize="10" fill="var(--fg-dim)"
                fontFamily="var(--mono)">
            {hover.label}
            {hover.value != null && ` · ${hover.value.toFixed(2)}×`}
          </text>
        </g>
      )}
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Grouped bars — 2 series × 4 categories (approaches)
// ═══════════════════════════════════════════════════════════════════

interface GroupedBarsProps {
  categories: string[];   // e.g. ['N','S','E','W']
  seriesA: { label: string; color: string; values: number[] };
  seriesB: { label: string; color: string; values: number[] };
  yLabel?: string;
  unit?: string;
  width?: number;
  height?: number;
}

export function GroupedBars({
  categories, seriesA, seriesB, yLabel, unit, width = 820, height = 260,
}: GroupedBarsProps) {
  const pad = { top: 22, right: 20, bottom: 40, left: 52 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const nCats = categories.length;
  const groupW = plotW / Math.max(1, nCats);
  const gap = 8;
  const barW = Math.max(8, (groupW - gap * 3) / 2);

  const maxY = Math.max(
    1, ...seriesA.values, ...seriesB.values,
  );
  const tickBase = Math.pow(10, Math.floor(Math.log10(Math.max(1, maxY))));
  const niceMax = Math.ceil(maxY / tickBase) * tickBase;
  const yTicks = 4;
  const yOf = (v: number) => pad.top + plotH - (v / niceMax) * plotH;

  return (
    <svg viewBox={`0 0 ${width} ${height}`}
         style={{ width: '100%', height: 'auto', maxWidth: width }}>
      {/* Y-axis grid */}
      {Array.from({ length: yTicks + 1 }, (_, i) => {
        const v = (niceMax / yTicks) * i;
        const y = yOf(v);
        return (
          <g key={i}>
            <line x1={pad.left} x2={width - pad.right} y1={y} y2={y}
                  stroke="var(--border-soft)" strokeDasharray="2 4" />
            <text x={pad.left - 6} y={y + 3} textAnchor="end"
                  fontSize="10" fill="var(--fg-faint)"
                  fontFamily="var(--mono)">
              {v.toFixed(niceMax < 10 ? 1 : 0)}
            </text>
          </g>
        );
      })}
      {yLabel && (
        <text x={pad.left - 38} y={pad.top + plotH / 2}
              fontSize="10" fill="var(--fg-faint)" fontFamily="var(--mono)"
              transform={`rotate(-90 ${pad.left - 38} ${pad.top + plotH / 2})`}
              textAnchor="middle">
          {yLabel}
        </text>
      )}

      {/* Bars + category labels */}
      {categories.map((cat, i) => {
        const gx = pad.left + i * groupW + gap;
        const vA = seriesA.values[i] ?? 0;
        const vB = seriesB.values[i] ?? 0;
        const hA = plotH - (yOf(vA) - pad.top);
        const hB = plotH - (yOf(vB) - pad.top);
        return (
          <g key={cat}>
            <rect x={gx} y={yOf(vA)} width={barW} height={hA}
                  fill={seriesA.color} opacity={0.85} />
            <rect x={gx + barW + gap} y={yOf(vB)} width={barW} height={hB}
                  fill={seriesB.color} opacity={0.85} />
            <text x={gx + (barW * 2 + gap) / 2}
                  y={height - pad.bottom + 16}
                  fontSize="12" fill="var(--fg)"
                  fontFamily="var(--mono)" fontWeight="600"
                  textAnchor="middle">
              {cat}
            </text>
            <text x={gx + barW / 2} y={yOf(vA) - 4}
                  fontSize="9" fill={seriesA.color}
                  fontFamily="var(--mono)" textAnchor="middle">
              {vA.toFixed(niceMax < 10 ? 2 : 0)}{unit}
            </text>
            <text x={gx + barW + gap + barW / 2} y={yOf(vB) - 4}
                  fontSize="9" fill={seriesB.color}
                  fontFamily="var(--mono)" textAnchor="middle">
              {vB.toFixed(niceMax < 10 ? 2 : 0)}{unit}
            </text>
          </g>
        );
      })}

      {/* Legend */}
      <g transform={`translate(${pad.left}, ${pad.top - 14})`}>
        <rect x={0} y={0} width={9} height={9} fill={seriesA.color} />
        <text x={14} y={8} fontSize="10" fill="var(--fg-dim)"
              fontFamily="var(--mono)">
          {seriesA.label}
        </text>
        <rect x={120} y={0} width={9} height={9} fill={seriesB.color} />
        <text x={134} y={8} fontSize="10" fill="var(--fg-dim)"
              fontFamily="var(--mono)">
          {seriesB.label}
        </text>
      </g>
    </svg>
  );
}

// Legend row for approach colors — shared across line charts
export function ApproachLegend() {
  return (
    <div style={{
      display: 'flex', gap: 14, flexWrap: 'wrap',
      font: '500 11px var(--mono)', color: 'var(--fg-dim)',
      marginBottom: 6,
    }}>
      {APPROACHES.map((a) => (
        <span key={a} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            display: 'inline-block', width: 10, height: 10,
            background: APPROACH_COLOR[a], borderRadius: 2,
          }} />
          {a} approach
        </span>
      ))}
    </div>
  );
}
