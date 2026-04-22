import type { CongestionLabel } from '../api/types';

const PALETTE: Record<string, { bg: string; fg: string }> = {
  free:     { bg: '#14532d', fg: '#86efac' },
  light:    { bg: '#1e40af', fg: '#bfdbfe' },
  moderate: { bg: '#78350f', fg: '#fde68a' },
  heavy:    { bg: '#7c2d12', fg: '#fdba74' },
  jam:      { bg: '#7f1d1d', fg: '#fecaca' },
};

interface Props {
  label: CongestionLabel | string | null | undefined;
}

export function Pill({ label }: Props) {
  const key = String(label ?? 'free').toLowerCase();
  const c = PALETTE[key] ?? { bg: '#1e2630', fg: '#e6edf3' };
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        background: c.bg,
        color: c.fg,
        textTransform: 'capitalize',
      }}
    >
      {label ?? '-'}
    </span>
  );
}

export const PILL_COLORS = PALETTE;
