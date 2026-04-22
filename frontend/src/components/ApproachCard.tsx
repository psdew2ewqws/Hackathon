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
        </div>
      </div>
    </div>
  );
}

function fmt(n: number | undefined | null, digits: number): string {
  if (n == null || !Number.isFinite(n)) return '-';
  return n.toFixed(digits);
}
