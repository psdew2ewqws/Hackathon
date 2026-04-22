import { memo } from 'react';
import type { EvalRow, PhaseNumber } from '../api/forecast';
import { PHASE_NAMES } from '../api/forecast';
import styles from '../pages/SignalTimingPage.module.css';

interface Props {
  phase: PhaseNumber;
  greenSeconds: number;
  rows: EvalRow[];       // 2 rows per phase (one per approach in that phase)
  onChange: (phase: PhaseNumber, greenSeconds: number) => void;
  websterRecommended?: number;
  minGreen?: number;
  maxGreen?: number;
}

function signalClassName(row: EvalRow | undefined): string {
  if (!row) return '';
  if (row.signal_color === 'green')  return styles.sigGreen;
  if (row.signal_color === 'yellow') return styles.sigYellow;
  if (row.signal_color === 'red')    return styles.sigRed;
  return '';
}

export const PhaseCard = memo(function PhaseCard({
  phase,
  greenSeconds,
  rows,
  onChange,
  websterRecommended,
  minGreen = 7,
  maxGreen = 60,
}: Props) {
  // Pick the "worst" row (highest v/c) for colour framing
  const worst = rows.reduce<EvalRow | undefined>(
    (acc, r) => (!acc || r.x > acc.x ? r : acc),
    undefined,
  );

  return (
    <div className={`${styles.phase} ${signalClassName(worst)}`}>
      <div className={styles.phaseTag}>Phase {phase}</div>
      <div className={styles.phaseName}>{PHASE_NAMES[phase]}</div>
      <input
        className={styles.phaseSlider}
        type="range"
        min={minGreen}
        max={maxGreen}
        step={1}
        value={greenSeconds}
        onChange={(e) => onChange(phase, Number(e.target.value))}
        aria-label={`Green time for phase ${phase}`}
      />
      <div className={styles.gVal}>
        {greenSeconds}
        <span className={styles.gValUnit}>s green</span>
      </div>
      <div className={styles.phaseStats}>
        {rows.map((r) => (
          <div key={`${r.approach}-${r.phase}`}>
            <span className="k" style={{ color: 'var(--fg-faint)', marginRight: 6 }}>
              {r.approach}:
            </span>
            <span>v/c {r.x.toFixed(2)}</span>
            <span style={{ color: 'var(--fg-mute)', margin: '0 6px' }}>·</span>
            <span>delay {r.delay_s.toFixed(0)}s</span>
          </div>
        ))}
        {websterRecommended !== undefined && (
          <div style={{ color: 'var(--fg-mute)', marginTop: 2 }}>
            Webster: {websterRecommended}s
          </div>
        )}
      </div>
    </div>
  );
});
