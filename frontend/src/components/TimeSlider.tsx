import { slotToHhmm, hhmmToSlot } from '../api/forecast';
import styles from '../pages/SignalTimingPage.module.css';

interface Props {
  value: string;               // "HH:MM"
  onChange: (hhmm: string) => void;
  minSlot?: number;            // 0 = 00:00
  maxSlot?: number;            // 47 = 23:30
}

export function TimeSlider({
  value,
  onChange,
  minSlot = 0,
  maxSlot = 47,
}: Props) {
  const idx = Math.max(minSlot, Math.min(maxSlot, hhmmToSlot(value)));
  return (
    <div className={styles.sliderWrap}>
      <label htmlFor="time-slider">Time</label>
      <input
        id="time-slider"
        type="range"
        min={minSlot}
        max={maxSlot}
        step={1}
        value={idx}
        onChange={(e) => onChange(slotToHhmm(Number(e.target.value)))}
        aria-label="Time of day"
      />
      <span className={styles.sliderNow}>{value}</span>
    </div>
  );
}
