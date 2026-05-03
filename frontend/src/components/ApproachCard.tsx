import { useEffect, useRef, useState } from 'react';
import { APPROACH_COLOR, type Approach, type FusedRow } from '../api/types';
import { Pill } from './Pill';

interface Props {
  approach: Approach;
  inZone: number;
  crossingsTotal: number;
  crossingsInBin: number;
  fused?: FusedRow;
}

export function ApproachCard({
  approach,
  inZone,
  crossingsTotal,
  crossingsInBin,
  fused,
}: Props) {
  // Pulse the bin-delta figure whenever it ticks up.
  const [pulse, setPulse] = useState(false);
  const prev = useRef(crossingsInBin);
  useEffect(() => {
    if (crossingsInBin > prev.current) {
      setPulse(true);
      const t = setTimeout(() => setPulse(false), 500);
      prev.current = crossingsInBin;
      return () => clearTimeout(t);
    }
    prev.current = crossingsInBin;
  }, [crossingsInBin]);

  const color = APPROACH_COLOR[approach];
  return (
    <div
      style={{
        background: '#121820',
        border: '1px solid #1e2630',
        borderRadius: 10,
        padding: 12,
        display: 'grid',
        gridTemplateColumns: '48px 1fr',
        gap: 10,
      }}
    >
      <div
        style={{
          fontSize: 34,
          fontWeight: 700,
          color,
          textAlign: 'center',
          lineHeight: 1,
          alignSelf: 'center',
        }}
      >
        {approach}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', gap: 12, fontSize: 13 }}>
          <span>
            <span style={{ opacity: 0.6 }}>in&nbsp;zone</span>{' '}
            <strong>{inZone}</strong>
          </span>
          <span>
            <span style={{ opacity: 0.6 }}>bin</span>{' '}
            <strong
              style={{
                color: pulse ? color : '#e6edf3',
                transition: 'color .4s ease',
              }}
            >
              +{crossingsInBin}
            </strong>
          </span>
          <span>
            <span style={{ opacity: 0.6 }}>total</span>{' '}
            <strong>{crossingsTotal}</strong>
          </span>
        </div>
        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            fontSize: 12,
            flexWrap: 'wrap',
          }}
        >
          <Pill label={fused?.gmaps_label ?? 'free'} />
          <span style={{ opacity: 0.7 }}>
            r={fmt(fused?.gmaps_congestion_ratio, 2)}
          </span>
          <span style={{ opacity: 0.7 }}>
            {fmt(fused?.gmaps_speed_kmh, 1)} km/h
          </span>
        </div>
        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            fontSize: 12,
          }}
        >
          <Pill label={fused?.label ?? 'free'} />
          <span style={{ opacity: 0.7 }}>pressure={fmt(fused?.pressure, 2)}</span>
          {fused?.in_zone_pce != null && (
            <span style={{ opacity: 0.55 }}>
              PCE={fmt(fused.in_zone_pce, 1)}
            </span>
          )}
        </div>
        {fused?.mix && Object.keys(fused.mix).length > 0 && (
          <ClassMixBar mix={fused.mix} />
        )}
      </div>
    </div>
  );
}

const CLASS_COLOR: Record<string, string> = {
  car: '#4ade80',         // green
  truck: '#60a5fa',       // blue
  bus: '#f472b6',         // pink
  motorcycle: '#fbbf24',  // amber
  bicycle: '#a78bfa',     // violet
  person: '#fb923c',      // orange
};

function ClassMixBar({ mix }: { mix: Record<string, number> }) {
  const total = Object.values(mix).reduce((a, b) => a + b, 0);
  if (total === 0) return null;
  const entries = Object.entries(mix).sort(
    ([, a], [, b]) => b - a,
  );
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div
        style={{
          display: 'flex',
          height: 6,
          borderRadius: 3,
          overflow: 'hidden',
          background: '#1e2630',
        }}
        title={entries.map(([k, v]) => `${k}: ${v}`).join('  ')}
      >
        {entries.map(([cls, n]) => (
          <div
            key={cls}
            style={{
              width: `${(n / total) * 100}%`,
              background: CLASS_COLOR[cls.toLowerCase()] ?? '#94a3b8',
            }}
          />
        ))}
      </div>
      <div
        style={{
          display: 'flex',
          gap: 8,
          fontSize: 11,
          opacity: 0.7,
          flexWrap: 'wrap',
        }}
      >
        {entries.map(([cls, n]) => (
          <span key={cls}>
            <span
              style={{
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: 2,
                background: CLASS_COLOR[cls.toLowerCase()] ?? '#94a3b8',
                marginRight: 4,
              }}
            />
            {cls}&nbsp;{n}
          </span>
        ))}
      </div>
    </div>
  );
}

function fmt(n: number | undefined | null, digits: number): string {
  if (n == null || !Number.isFinite(n)) return '-';
  return n.toFixed(digits);
}
