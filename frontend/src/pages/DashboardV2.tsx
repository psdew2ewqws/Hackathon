import { useState } from 'react';
import { AIPipelineStrip } from '../components/v2/AIPipelineStrip';
import { AIStackPanel } from '../components/v2/AIStackPanel';
import { ForecastStrip } from '../components/v2/ForecastStrip';
import { HeatmapPanel } from '../components/v2/HeatmapPanel';
import { LiveEventsPanel } from '../components/v2/LiveEventsPanel';
import { LiveFeedPanel } from '../components/v2/LiveFeedPanel';
import { LiveKpiRow } from '../components/v2/LiveKpiRow';
import { LiveSignalState } from '../components/v2/LiveSignalState';
import { OperatorTopBar } from '../components/v2/OperatorTopBar';
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
        position: 'relative',
        zIndex: 1,
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <OperatorTopBar />

      <main
        style={{
          flex: 1,
          padding: '14px 18px 36px',
          display: 'grid',
          gridTemplateColumns: '1fr',
          gap: 12,
        }}
      >
        {/* Hero · Live feed (62%) | AI stack (38%) */}
        <div
          className="rise rise-d-1"
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1.62fr) minmax(360px, 1fr)',
            gap: 12,
          }}
        >
          <LiveFeedPanel />
          <AIStackPanel />
        </div>

        {/* Pipeline strip */}
        <div className="rise rise-d-2">
          <AIPipelineStrip />
        </div>

        {/* KPIs (auto-fits) + signal state */}
        <div
          className="rise rise-d-3"
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1.55fr) minmax(0, 1fr)',
            gap: 12,
          }}
        >
          <LiveKpiRow />
          <LiveSignalState />
        </div>

        {/* Heatmap full width */}
        <div className="rise rise-d-4">
          <HeatmapPanel selectedHour={selectedHour} onSelectHour={setSelectedHour} />
        </div>

        {/* Forecast | Webster side-by-side */}
        <div
          className="rise rise-d-5"
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.2fr)',
            gap: 12,
          }}
        >
          <ForecastStrip />
          <WebsterBar />
        </div>

        {/* Events row */}
        <div
          className="rise rise-d-6"
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
            gap: 12,
          }}
        >
          <LiveEventsPanel />
          <RecentSignalPanel />
        </div>
      </main>
    </div>
  );
}
