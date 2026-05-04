import { useState } from 'react';
import { ForecastStrip } from '../components/v2/ForecastStrip';
import { HeatmapPanel } from '../components/v2/HeatmapPanel';
import { LiveEventsPanel } from '../components/v2/LiveEventsPanel';
import { LiveFeedPanel } from '../components/v2/LiveFeedPanel';
import { LiveKpiRow } from '../components/v2/LiveKpiRow';
import { LiveSignalState } from '../components/v2/LiveSignalState';
import { RecentSignalPanel } from '../components/v2/RecentSignalPanel';
import { WebsterBar } from '../components/v2/WebsterBar';

function nowHalfHour(): number {
  const d = new Date();
  const h = d.getHours() + Math.floor(d.getMinutes() / 30) * 0.5;
  return Math.max(0, Math.min(23.5, h));
}

export function DashboardV2() {
  const [selectedHour, setSelectedHour] = useState<number>(nowHalfHour());

  return (
    <div
      style={{
        maxWidth: 1440,
        margin: '0 auto',
        padding: '20px 24px 60px',
        color: 'var(--fg)',
      }}
    >
      <div style={{ marginBottom: 16 }}>
        <h1
          style={{
            font: '600 22px var(--sans)',
            margin: 0,
            color: 'var(--fg)',
            letterSpacing: '-0.01em',
          }}
        >
          Wadi Saqra · Dashboard
        </h1>
        <div
          style={{
            font: '400 12px var(--mono)',
            color: 'var(--fg-faint)',
            marginTop: 2,
          }}
        >
          live feed · KPIs · signal phase · 24h heatmap · forecast horizons · webster · events
        </div>
      </div>

      {/* Top row: live feed (left) | KPIs + signal state (right) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)',
          gap: 14,
          marginBottom: 14,
        }}
      >
        <LiveFeedPanel />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <LiveKpiRow />
          <LiveSignalState />
        </div>
      </div>

      <HeatmapPanel selectedHour={selectedHour} onSelectHour={setSelectedHour} />
      <ForecastStrip />
      <WebsterBar />

      {/* Bottom row: live events | recent signal events */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
          gap: 14,
        }}
      >
        <LiveEventsPanel />
        <RecentSignalPanel />
      </div>
    </div>
  );
}
