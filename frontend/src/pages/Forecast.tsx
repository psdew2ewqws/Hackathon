import { useEffect, useMemo, useRef, useState } from 'react';
import { getForecast, getHeatmap } from '../api/client';
import {
  APPROACHES,
  APPROACH_COLOR,
  type Approach,
  type ForecastResponse,
  type HeatmapResponse,
} from '../api/types';
import { ApproachCard } from '../components/ApproachCard';

const LABEL_COLORS: Record<string, string> = {
  free:     '#14532d',
  light:    '#1e40af',
  moderate: '#78350f',
  heavy:    '#7c2d12',
  jam:      '#7f1d1d',
};
const EMPTY_COLOR = '#1e2630';

const ROW_ORDER: Approach[] = APPROACHES; // S, N, E, W

function formatHHMM(h: number): string {
  const hh = Math.floor(h);
  const mm = h % 1 === 0.5 ? 30 : 0;
  return `${hh.toString().padStart(2, '0')}:${mm.toString().padStart(2, '0')}`;
}

export function ForecastPage() {
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null);
  const [selectedHour, setSelectedHour] = useState<number>(10);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Load heatmap once
  useEffect(() => {
    const ac = new AbortController();
    getHeatmap(ac.signal)
      .then((h) => {
        setHeatmap(h);
        if (typeof h.current_hour === 'number') {
          setSelectedHour(h.current_hour);
        }
      })
      .catch((e) => setErr(String((e as Error).message ?? e)));
    return () => ac.abort();
  }, []);

  // Debounced forecast fetch on slider change
  const debounceRef = useRef<number | null>(null);
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const ac = new AbortController();
    debounceRef.current = window.setTimeout(() => {
      getForecast(selectedHour, ac.signal)
        .then(setForecast)
        .catch(() => {
          /* abort is expected; other errors surfaced via heatmap */
        });
    }, 150);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      ac.abort();
    };
  }, [selectedHour]);

  const hours = heatmap?.hours ?? [];
  const currentHour = heatmap?.current_hour;

  const selectedIdx = useMemo(() => {
    if (!hours.length) return -1;
    return hours.findIndex((h) => Math.abs(h - selectedHour) < 1e-6);
  }, [hours, selectedHour]);
  const currentIdx = useMemo(() => {
    if (!hours.length || currentHour == null) return -1;
    return hours.findIndex((h) => Math.abs(h - currentHour) < 1e-6);
  }, [hours, currentHour]);

  if (err && !heatmap) {
    return <div style={{ padding: 18, color: '#fecaca' }}>Error: {err}</div>;
  }
  if (!heatmap) {
    return <div style={{ padding: 18, opacity: 0.7 }}>Loading heatmap…</div>;
  }

  return (
    <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <SliderBar
        hour={selectedHour}
        currentHour={currentHour ?? null}
        onChange={setSelectedHour}
      />

      <section
        style={{
          background: '#121820',
          border: '1px solid #1e2630',
          borderRadius: 10,
          padding: 12,
          overflowX: 'auto',
        }}
      >
        <h3 style={cardTitle}>24h pressure heatmap</h3>
        <Heatmap
          heatmap={heatmap}
          selectedIdx={selectedIdx}
          currentIdx={currentIdx}
        />
        <Legend />
      </section>

      <section style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <h3 style={cardTitle}>
          Predicted at {formatHHMM(selectedHour)}
          {forecast && (
            <span style={{ opacity: 0.55, fontWeight: 400, marginLeft: 8 }}>
              (baseline {formatHHMM(forecast.baseline_hour)})
            </span>
          )}
        </h3>
        {!forecast ? (
          <div style={{ opacity: 0.6, fontSize: 13 }}>Loading forecast…</div>
        ) : (
          <>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                gap: 10,
              }}
            >
              {ROW_ORDER.map((a) => {
                const row = forecast.predicted[a];
                return (
                  <ApproachCard
                    key={a}
                    approach={a}
                    inZone={row?.in_zone ?? 0}
                    crossingsTotal={0}
                    crossingsInBin={row?.crossings_in_bin ?? 0}
                    fused={row}
                  />
                );
              })}
            </div>
            <ForecastPlan forecast={forecast} />
          </>
        )}
      </section>
    </div>
  );
}

const cardTitle: React.CSSProperties = {
  fontSize: 13,
  margin: '0 0 10px',
  letterSpacing: '.06em',
  textTransform: 'uppercase',
  opacity: 0.7,
};

function SliderBar({
  hour,
  currentHour,
  onChange,
}: {
  hour: number;
  currentHour: number | null;
  onChange: (h: number) => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 14,
        alignItems: 'center',
        padding: '12px 14px',
        background: '#121820',
        border: '1px solid #1e2630',
        borderRadius: 10,
        flexWrap: 'wrap',
      }}
    >
      <strong style={{ fontSize: 16 }}>{formatHHMM(hour)}</strong>
      <input
        type="range"
        min={0}
        max={23.5}
        step={0.5}
        value={hour}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ flex: 1, minWidth: 240 }}
      />
      {currentHour != null && (
        <button
          onClick={() => onChange(currentHour)}
          style={{
            background: '#1e2630',
            color: '#e6edf3',
            border: '1px solid #2a3440',
            borderRadius: 6,
            padding: '6px 10px',
            fontSize: 12,
          }}
        >
          Now ({formatHHMM(currentHour)})
        </button>
      )}
    </div>
  );
}

function Heatmap({
  heatmap,
  selectedIdx,
  currentIdx,
}: {
  heatmap: HeatmapResponse;
  selectedIdx: number;
  currentIdx: number;
}) {
  const { hours, cells } = heatmap;
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `48px repeat(${hours.length}, minmax(22px, 1fr))`,
        gap: 2,
        minWidth: 1000,
        position: 'relative',
      }}
    >
      {/* top axis */}
      <div />
      {hours.map((h, i) => (
        <div
          key={`top-${i}`}
          style={{
            fontSize: 10,
            textAlign: 'center',
            opacity: h % 1 === 0 ? 0.8 : 0.3,
          }}
        >
          {h % 1 === 0 ? h.toString().padStart(2, '0') : ''}
        </div>
      ))}

      {/* approach rows */}
      {ROW_ORDER.map((a) => (
        // eslint-disable-next-line react/jsx-key
        <HeatmapRow
          key={a}
          approach={a}
          row={cells[a] ?? []}
          selectedIdx={selectedIdx}
          currentIdx={currentIdx}
        />
      ))}
    </div>
  );
}

function HeatmapRow({
  approach,
  row,
  selectedIdx,
  currentIdx,
}: {
  approach: Approach;
  row: HeatmapResponse['cells'][Approach];
  selectedIdx: number;
  currentIdx: number;
}) {
  return (
    <>
      <div
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: APPROACH_COLOR[approach],
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: 34,
        }}
      >
        {approach}
      </div>
      {row.map((cell, i) => {
        const label = cell.label ? String(cell.label).toLowerCase() : null;
        const bg =
          label && LABEL_COLORS[label]
            ? LABEL_COLORS[label]
            : cell.pressure == null
              ? EMPTY_COLOR
              : '#1e2630';
        const isSelected = i === selectedIdx;
        const isCurrent = i === currentIdx;
        const tooltip =
          `${approach} · ${formatHHMM(cell.hour)}\n` +
          `pressure: ${cell.pressure?.toFixed(2) ?? 'n/a'}\n` +
          `gmaps ratio: ${cell.gmaps_ratio?.toFixed(2) ?? 'n/a'} (${cell.gmaps_label ?? 'n/a'})\n` +
          `speed: ${cell.gmaps_speed_kmh?.toFixed(1) ?? 'n/a'} km/h`;
        return (
          <div
            key={`${approach}-${i}`}
            title={tooltip}
            style={{
              background: bg,
              height: 34,
              borderRadius: 3,
              position: 'relative',
              outline: isSelected ? '2px solid #e6edf3' : 'none',
              outlineOffset: isSelected ? -1 : 0,
              boxShadow: isCurrent && !isSelected ? 'inset 0 0 0 1px #f5a53c' : 'none',
              opacity: cell.pressure == null ? 0.5 : 1,
            }}
          />
        );
      })}
    </>
  );
}

function Legend() {
  return (
    <div
      style={{
        display: 'flex',
        gap: 14,
        alignItems: 'center',
        flexWrap: 'wrap',
        marginTop: 10,
        fontSize: 12,
      }}
    >
      {(['free', 'light', 'moderate', 'heavy', 'jam'] as const).map((k) => (
        <span
          key={k}
          style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}
        >
          <span
            style={{
              width: 14,
              height: 14,
              background: LABEL_COLORS[k],
              borderRadius: 3,
            }}
          />
          {k}
        </span>
      ))}
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', opacity: 0.8 }}>
        <span
          style={{
            width: 14,
            height: 14,
            background: EMPTY_COLOR,
            borderRadius: 3,
            opacity: 0.5,
          }}
        />
        missing
      </span>
      <span style={{ opacity: 0.7, marginLeft: 8 }}>
        outlined = selected hour &nbsp;·&nbsp; orange border = current hour
      </span>
    </div>
  );
}

function ForecastPlan({ forecast }: { forecast: ForecastResponse }) {
  const cmp = forecast.recommendation?.comparison;
  if (!cmp) return null;
  const delta = cmp.delay_reduction_pct ?? 0;
  const deltaColor = delta >= 0 ? '#66ff88' : '#ff7a7a';
  return (
    <div
      style={{
        background: '#121820',
        border: '1px solid #1e2630',
        borderRadius: 10,
        padding: 12,
        marginTop: 4,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 12,
          marginBottom: 10,
          flexWrap: 'wrap',
        }}
      >
        <h4 style={{ margin: 0, fontSize: 14 }}>
          Webster plan @ {formatHHMM(forecast.requested_hour)}
        </h4>
        <span
          style={{
            padding: '2px 8px',
            borderRadius: 999,
            background: '#1e2630',
            color: deltaColor,
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {delta >= 0 ? '−' : '+'}
          {Math.abs(delta).toFixed(1)}% delay
        </span>
      </div>
      <table
        style={{
          width: '100%',
          maxWidth: 640,
          fontSize: 13,
          borderCollapse: 'collapse',
        }}
      >
        <thead>
          <tr style={{ opacity: 0.7, textAlign: 'left' }}>
            <th style={th}>Plan</th>
            <th style={th}>NS green</th>
            <th style={th}>EW green</th>
            <th style={th}>Cycle</th>
            <th style={th}>Delay (s/veh)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={td}>Current (field)</td>
            <td style={td}>{cmp.current.NS_green.toFixed(1)}s</td>
            <td style={td}>{(cmp.current.EW_green ?? 0).toFixed(1)}s</td>
            <td style={td}>{cmp.current.cycle_seconds.toFixed(1)}s</td>
            <td style={td}>{cmp.current.uniform_delay_sec_per_veh.toFixed(2)}</td>
          </tr>
          <tr>
            <td style={{ ...td, color: '#66ff88', fontWeight: 600 }}>Predicted</td>
            <td style={td}>{cmp.recommended.NS_green.toFixed(1)}s</td>
            <td style={td}>{(cmp.recommended.EW_green ?? 0).toFixed(1)}s</td>
            <td style={td}>{cmp.recommended.cycle_seconds.toFixed(1)}s</td>
            <td style={td}>{cmp.recommended.uniform_delay_sec_per_veh.toFixed(2)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

const th: React.CSSProperties = {
  padding: '6px 8px',
  borderBottom: '1px solid #1e2630',
  fontWeight: 500,
};
const td: React.CSSProperties = {
  padding: '6px 8px',
  borderBottom: '1px solid #1e2630',
};
