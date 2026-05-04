import { useCallback, useEffect, useState } from 'react';
import { getHeatmap } from '../../api/client';
import {
  APPROACHES,
  type Approach,
  type CongestionLabel,
  type HeatmapResponse,
} from '../../api/types';

const LABEL_COLOR: Record<string, string> = {
  free: '#7FA889',
  light: '#E8B464',
  moderate: '#D68F6B',
  heavy: '#D68F6B',
  jam: '#E46F6F',
  unknown: '#3E444D',
};

function colorFor(label: CongestionLabel | null): string {
  if (!label) return LABEL_COLOR.unknown;
  return LABEL_COLOR[label] ?? LABEL_COLOR.unknown;
}

function hourLabel(h: number): string {
  const hh = Math.floor(h);
  const mm = Math.round((h - hh) * 60);
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}

interface Props {
  selectedHour: number;
  onSelectHour: (h: number) => void;
}

export function HeatmapPanel({ selectedHour, onSelectHour }: Props) {
  const [data, setData] = useState<HeatmapResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getHeatmap();
      setData(r);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const hours = data?.hours ?? [];
  const nSlots = hours.length || 48;

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
          marginBottom: 12,
        }}
      >
        <div>
          <div
            style={{
              font: '600 11px var(--mono)',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--fg-dim)',
            }}
          >
            24-hour gmaps heatmap
          </div>
          <div
            style={{
              font: '400 11px var(--mono)',
              color: 'var(--fg-faint)',
              marginTop: 2,
            }}
          >
            48 half-hour bins · 4 corridors · click to drill into the forecast strip
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span
            style={{
              font: '500 10px var(--mono)',
              color: 'var(--fg-faint)',
            }}
          >
            selected · {hourLabel(selectedHour)}
          </span>
          <button
            onClick={load}
            disabled={loading}
            style={{
              font: '500 11px var(--mono)',
              color: 'var(--fg-dim)',
              background: 'transparent',
              border: '1px solid var(--border-soft)',
              borderRadius: 6,
              padding: '4px 10px',
              cursor: loading ? 'wait' : 'pointer',
            }}
          >
            {loading ? '…' : 'refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            font: '500 11px var(--mono)',
            color: 'var(--bad)',
            marginBottom: 8,
          }}
        >
          {error}
        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `28px repeat(${nSlots}, 1fr)`,
          gap: 1,
          marginBottom: 4,
        }}
      >
        <div />
        {hours.map((h, i) => (
          <div
            key={i}
            style={{
              font: '500 9px var(--mono)',
              color: i % 4 === 0 ? 'var(--fg-faint)' : 'transparent',
              textAlign: 'left',
              letterSpacing: '-0.02em',
            }}
          >
            {i % 4 === 0 ? String(Math.floor(h)).padStart(2, '0') : ''}
          </div>
        ))}
      </div>

      {APPROACHES.map((a) => {
        const cells = data?.cells?.[a as Approach] ?? [];
        return (
          <div
            key={a}
            style={{
              display: 'grid',
              gridTemplateColumns: `28px repeat(${nSlots}, 1fr)`,
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
            {hours.map((h, i) => {
              const cell = cells[i];
              const label = cell?.gmaps_label ?? null;
              const isSelected = Math.abs(h - selectedHour) < 0.001;
              return (
                <button
                  key={i}
                  onClick={() => onSelectHour(h)}
                  title={`${a} @ ${hourLabel(h)} · ${cell?.gmaps_label ?? '—'}${
                    cell?.gmaps_ratio != null
                      ? ` · ratio ${cell.gmaps_ratio.toFixed(2)}`
                      : ''
                  }${cell?.gmaps_speed_kmh != null ? ` · ${cell.gmaps_speed_kmh.toFixed(1)} km/h` : ''}`}
                  style={{
                    height: 16,
                    background: colorFor(label),
                    border: isSelected
                      ? '2px solid var(--fg)'
                      : '1px solid rgba(255,255,255,0.05)',
                    borderRadius: 2,
                    padding: 0,
                    cursor: 'pointer',
                    transition: 'transform 0.08s',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = 'scaleY(1.5)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = 'scaleY(1)';
                  }}
                  aria-label={`${a} approach at ${hourLabel(h)}, ${label ?? 'unknown'}`}
                />
              );
            })}
          </div>
        );
      })}

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
          <span key={k} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
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
    </div>
  );
}
