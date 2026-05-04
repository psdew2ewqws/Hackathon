import { useEffect, useMemo, useState } from 'react';
import { getForecastMl } from '../../api/client';
import {
  APPROACH_COLOR,
  type Approach,
  type ForecastMlPerDetector,
  type ForecastMlResponse,
} from '../../api/types';

interface Row {
  detector_id: string;
  approach: Approach;
  lane_idx: number;
  y_now: number;
  y_60min: number;
  delta_pct: number | null;
}

function parseDetectorId(id: string): { approach: Approach; lane_idx: number; sub_idx: number } | null {
  // Format: DET-{approach}-{lane}-{idx}
  const m = id.match(/^DET-([NSEW])-(\d+)-(\d+)$/);
  if (!m) return null;
  return {
    approach: m[1] as Approach,
    lane_idx: parseInt(m[2], 10),
    sub_idx: parseInt(m[3], 10),
  };
}

interface Props {
  closures: Record<Approach, boolean>;
  onToggleClosure: (approach: Approach) => void;
}

export function PerLaneForecastTable({ closures, onToggleClosure }: Props) {
  const [data, setData] = useState<ForecastMlResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getForecastMl();
        if (alive) {
          setData(r);
          setError(null);
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    tick();
    const id = window.setInterval(tick, 60_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const rows: Row[] = useMemo(() => {
    if (!data?.per_detector) return [];
    const out: Row[] = [];
    for (const [id, det] of Object.entries(data.per_detector)) {
      const parsed = parseDetectorId(id);
      if (!parsed) continue;
      const d = det as ForecastMlPerDetector;
      const dlt = d.y_now > 0 ? ((d.y_60min - d.y_now) / d.y_now) * 100 : null;
      out.push({
        detector_id: id,
        approach: parsed.approach,
        lane_idx: parsed.lane_idx,
        y_now: d.y_now,
        y_60min: d.y_60min,
        delta_pct: dlt,
      });
    }
    out.sort(
      (a, b) =>
        a.approach.localeCompare(b.approach) || a.lane_idx - b.lane_idx ||
        a.detector_id.localeCompare(b.detector_id),
    );
    return out;
  }, [data]);

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 6,
        }}
      >
        <span
          style={{
            font: '600 11px var(--mono)',
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: 'var(--fg-bright)',
          }}
        >
          Per-lane forecast
        </span>
        <span
          style={{
            font: '500 10px var(--mono)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--fg-faint)',
          }}
        >
          {error ? 'reconnecting…' : 'LightGBM · now → +60min · click to close'}
        </span>
      </div>

      <div
        className="scroll-thin"
        style={{
          display: 'grid',
          gridTemplateColumns: '20px 1fr 56px 56px 70px',
          rowGap: 4,
          columnGap: 10,
          alignItems: 'center',
          maxHeight: 320,
          overflowY: 'auto',
          paddingRight: 4,
        }}
      >
        {/* header row */}
        <div />
        <span style={head}>detector</span>
        <span style={{ ...head, textAlign: 'right' }}>now</span>
        <span style={{ ...head, textAlign: 'right' }}>+60</span>
        <span style={{ ...head, textAlign: 'right' }}>Δ %</span>

        {rows.length === 0 && !error && (
          <div
            style={{
              gridColumn: '1 / -1',
              font: '500 11px var(--mono)',
              color: 'var(--fg-faint)',
              padding: '8px 0',
            }}
          >
            warming up — LightGBM forecast loading…
          </div>
        )}

        {rows.map((r) => {
          const closed = closures[r.approach];
          const dToneCol =
            r.delta_pct == null
              ? 'var(--fg-faint)'
              : r.delta_pct > 8
              ? 'var(--bad)'
              : r.delta_pct < -8
              ? 'var(--good)'
              : 'var(--fg-dim)';
          const arrow =
            r.delta_pct == null ? '' : r.delta_pct > 8 ? '↑' : r.delta_pct < -8 ? '↓' : '→';
          return (
            <button
              key={r.detector_id}
              type="button"
              onClick={() => onToggleClosure(r.approach)}
              style={{
                display: 'contents',
                cursor: 'pointer',
                background: 'transparent',
                border: 'none',
                padding: 0,
                textAlign: 'left',
              }}
              title={`Click to toggle closure for ${r.approach} approach (currently ${
                closed ? 'CLOSED' : 'open'
              }).`}
            >
              <span
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: 3,
                  background: closed ? 'var(--bad)' : APPROACH_COLOR[r.approach],
                  display: 'inline-block',
                }}
              />
              <span
                style={{
                  font: '500 11px var(--mono)',
                  color: closed ? 'var(--bad)' : 'var(--fg)',
                  textDecoration: closed ? 'line-through' : 'none',
                }}
              >
                {r.detector_id}
              </span>
              <span
                className="tabular"
                style={{
                  font: '600 11px var(--mono)',
                  color: 'var(--fg)',
                  textAlign: 'right',
                }}
              >
                {r.y_now.toFixed(0)}
              </span>
              <span
                className="tabular"
                style={{
                  font: '600 11px var(--mono)',
                  color: 'var(--fg)',
                  textAlign: 'right',
                }}
              >
                {r.y_60min.toFixed(0)}
              </span>
              <span
                className="tabular"
                style={{
                  font: '600 11px var(--mono)',
                  color: dToneCol,
                  textAlign: 'right',
                }}
              >
                {r.delta_pct == null ? '—' : `${arrow} ${Math.abs(r.delta_pct).toFixed(0)}%`}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

const head: React.CSSProperties = {
  font: '600 9px var(--mono)',
  letterSpacing: '0.16em',
  textTransform: 'uppercase',
  color: 'var(--fg-faint)',
};
