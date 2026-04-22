import type { ReactNode } from 'react';

interface Props {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: string;
}

export function StatBlock({ label, value, sub, accent }: Props) {
  return (
    <div
      style={{
        background: '#121820',
        border: '1px solid #1e2630',
        borderRadius: 10,
        padding: '12px 14px',
        minWidth: 120,
      }}
    >
      <div
        style={{
          fontSize: 11,
          letterSpacing: '.06em',
          textTransform: 'uppercase',
          opacity: 0.7,
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 26,
          fontWeight: 600,
          color: accent ?? '#e6edf3',
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
      {sub != null && (
        <div style={{ fontSize: 12, opacity: 0.65, marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}
