import { useMemo } from 'react';
import type { ForecastRow, CongestionLabel } from '../api/forecast';
import { slotToHhmm, hhmmToSlot } from '../api/forecast';

const APPROACHES = ['N', 'S', 'E', 'W'] as const;
const N_SLOTS = 48;

const LABEL_COLOR: Record<CongestionLabel, string> = {
  free:    '#7FA889',   // sage green
  light:   '#E8B464',   // amber
  heavy:   '#D68F6B',   // terracotta
  jam:     '#E46F6F',   // red
  unknown: '#3E444D',   // muted
};

interface Props {
  rows: ForecastRow[];
  currentHhmm: string;
  onSelect: (hhmm: string) => void;
}

export function DayHeatmap({ rows, currentHhmm, onSelect }: Props) {
  const byCell = useMemo(() => {
    const m: Record<string, ForecastRow> = {};
    for (const r of rows) m[`${r.approach}|${r.time}`] = r;
    return m;
  }, [rows]);

  const jamSlots = useMemo(() => {
    const out: Array<{ hhmm: string; approach: string; ratio: number }> = [];
    for (const r of rows) {
      if ((r.ratio ?? 0) >= 2.4) {
        out.push({ hhmm: r.time, approach: r.approach, ratio: r.ratio! });
      }
    }
    // Dedupe by hhmm keeping the max-ratio row
    const bySlot = new Map<string, { hhmm: string; approach: string; ratio: number }>();
    for (const j of out) {
      const prev = bySlot.get(j.hhmm);
      if (!prev || j.ratio > prev.ratio) bySlot.set(j.hhmm, j);
    }
    return Array.from(bySlot.values()).sort((a, b) => a.hhmm.localeCompare(b.hhmm));
  }, [rows]);

  const currentSlotIdx = hhmmToSlot(currentHhmm);

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '14px 16px',
        marginBottom: 14,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 10,
        }}
      >
        <div
          style={{
            font: '500 10px var(--mono)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--fg-faint)',
          }}
        >
          Day forecast ·{' '}
          <span style={{ color: 'var(--fg-dim)' }}>
            free / light / heavy / jam · click any cell to jump the simulator
          </span>
        </div>
        <div
          style={{
            font: '500 10px var(--mono)',
            color: 'var(--fg-faint)',
            letterSpacing: '0.04em',
          }}
        >
          {rows.length} predictions · Google typical-day
        </div>
      </div>

      {/* Hour labels along top */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `28px repeat(${N_SLOTS}, 1fr)`,
          gap: 1,
          marginBottom: 4,
        }}
      >
        <div />
        {Array.from({ length: N_SLOTS }, (_, i) => (
          <div
            key={i}
            style={{
              font: '500 9px var(--mono)',
              color: i % 4 === 0 ? 'var(--fg-faint)' : 'transparent',
              textAlign: 'left',
              letterSpacing: '-0.02em',
            }}
          >
            {i % 4 === 0 ? String(Math.floor(i / 2)).padStart(2, '0') : ''}
          </div>
        ))}
      </div>

      {/* 4 approach rows */}
      {APPROACHES.map((a) => (
        <div
          key={a}
          style={{
            display: 'grid',
            gridTemplateColumns: `28px repeat(${N_SLOTS}, 1fr)`,
            gap: 1,
            marginBottom: 2,
          }}
        >
          <div
            style={{
              font: '600 10px var(--mono)',
              color: 'var(--fg-dim)',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            {a}
          </div>
          {Array.from({ length: N_SLOTS }, (_, i) => {
            const hhmm = slotToHhmm(i);
            const row = byCell[`${a}|${hhmm}`];
            const label = row?.label ?? 'unknown';
            const color = LABEL_COLOR[label];
            const isCurrent = i === currentSlotIdx;
            return (
              <button
                key={i}
                onClick={() => onSelect(hhmm)}
                title={`${a} @ ${hhmm} — ${label}${row?.ratio ? ` (ratio ${row.ratio.toFixed(2)}×)` : ''}`}
                style={{
                  height: 14,
                  background: color,
                  border: isCurrent
                    ? '2px solid var(--fg)'
                    : '1px solid rgba(255,255,255,0.05)',
                  borderRadius: 2,
                  padding: 0,
                  cursor: 'pointer',
                  transition: 'transform 0.08s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'scaleY(1.6)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'scaleY(1)';
                }}
                aria-label={`${a} approach at ${hhmm}, ${label}`}
              />
            );
          })}
        </div>
      ))}

      {/* Legend */}
      <div
        style={{
          marginTop: 10,
          display: 'flex',
          gap: 14,
          font: '400 10px var(--mono)',
          color: 'var(--fg-faint)',
          letterSpacing: '0.02em',
        }}
      >
        {(['free', 'light', 'heavy', 'jam'] as const).map((k) => (
          <span
            key={k}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <span
              style={{
                width: 10,
                height: 10,
                background: LABEL_COLOR[k],
                borderRadius: 2,
                display: 'inline-block',
              }}
            />
            {k}
          </span>
        ))}
      </div>

      {/* Jam forecast summary */}
      {jamSlots.length > 0 && (
        <div
          style={{
            marginTop: 12,
            paddingTop: 10,
            borderTop: '1px solid var(--border-soft)',
            font: '400 11px var(--mono)',
            color: 'var(--fg-dim)',
          }}
        >
          <b style={{ color: 'var(--bad)' }}>Jam forecast:</b>{' '}
          {jamSlots.length} slot{jamSlots.length === 1 ? '' : 's'} with
          ratio ≥ 2.4×. Worst:{' '}
          {jamSlots
            .slice(0, 5)
            .map(
              (j) => `${j.hhmm} ${j.approach} (${j.ratio.toFixed(2)}×)`,
            )
            .join(', ')}
          {jamSlots.length > 5 ? ` … +${jamSlots.length - 5} more` : ''}
        </div>
      )}
    </div>
  );
}
