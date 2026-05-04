import { useEffect, useState } from 'react';
import { AIPipelineStrip } from '../components/v2/AIPipelineStrip';
import { AIStackPanel } from '../components/v2/AIStackPanel';
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

function useClock(): string {
  const [now, setNow] = useState<Date>(new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function DashboardV2() {
  const [selectedHour, setSelectedHour] = useState<number>(nowHalfHour());
  const clock = useClock();

  return (
    <div
      style={{
        position: 'relative',
        zIndex: 1,
        maxWidth: 1480,
        margin: '0 auto',
        padding: '24px 28px 60px',
        color: 'var(--fg)',
      }}
    >
      {/* ─── Editorial header ──────────────────────────────────────── */}
      <header
        className="rise"
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr auto',
          alignItems: 'flex-end',
          gap: 16,
          marginBottom: 22,
          paddingBottom: 18,
          borderBottom: '1px solid var(--border-soft)',
        }}
      >
        <div>
          <div
            style={{
              font: '600 9px var(--mono)',
              letterSpacing: '0.32em',
              textTransform: 'uppercase',
              color: 'var(--accent)',
              marginBottom: 8,
            }}
          >
            Wadi Saqra · operations
          </div>
          <h1
            style={{
              font: '400 56px/0.92 var(--display)',
              fontStyle: 'italic',
              margin: 0,
              letterSpacing: '-0.02em',
              color: 'var(--fg)',
            }}
          >
            traffic intel{' '}
            <span
              style={{
                fontStyle: 'normal',
                color: 'var(--fg-faint)',
                fontSize: '0.4em',
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                fontFamily: 'var(--mono)',
                fontWeight: 600,
                verticalAlign: 'middle',
                marginLeft: 14,
              }}
            >
              v2 · dashboard
            </span>
          </h1>
          <div
            style={{
              font: '400 13px var(--sans)',
              color: 'var(--fg-dim)',
              marginTop: 8,
              maxWidth: 700,
            }}
          >
            Six AI models, one signalised intersection.{' '}
            <span style={{ color: 'var(--ai)' }}>RF-DETR / YOLO</span> see the
            scene · <span style={{ color: 'var(--accent)' }}>ByteTrack</span>{' '}
            counts the cars · <span style={{ color: '#a78bfa' }}>LightGBM</span>{' '}
            predicts the next hour · <span style={{ color: '#7FA889' }}>Webster–HCM</span>{' '}
            recommends green-time splits · <span style={{ color: '#f0a5d4' }}>Claude/MCP</span>{' '}
            answers questions about all of it.
          </div>
        </div>
        <div
          style={{
            textAlign: 'right',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 4,
          }}
        >
          <div
            style={{
              font: '500 9px var(--mono)',
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              color: 'var(--fg-faint)',
            }}
          >
            local time · amman
          </div>
          <div
            style={{
              font: 'italic 400 38px var(--display)',
              color: 'var(--fg)',
              letterSpacing: '-0.01em',
              lineHeight: 1,
            }}
          >
            {clock}
          </div>
          <div
            style={{
              font: '500 9px var(--mono)',
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: 'var(--fg-faint)',
              marginTop: 2,
            }}
          >
            cycle 120s · 3-phase
          </div>
        </div>
      </header>

      {/* ─── Hero: Live feed (60%) | AI Stack (40%) ──────────────── */}
      <div
        className="rise rise-d-1"
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.55fr) minmax(360px, 1fr)',
          gap: 16,
          marginBottom: 16,
        }}
      >
        <LiveFeedPanel />
        <AIStackPanel />
      </div>

      {/* ─── Pipeline strip ──────────────────────────────────────── */}
      <div className="rise rise-d-2">
        <AIPipelineStrip />
      </div>

      {/* ─── KPIs + signal state ─────────────────────────────────── */}
      <div
        className="rise rise-d-3"
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)',
          gap: 14,
          marginBottom: 14,
        }}
      >
        <LiveKpiRow />
        <LiveSignalState />
      </div>

      {/* ─── Heatmap ─────────────────────────────────────────────── */}
      <div className="rise rise-d-4">
        <HeatmapPanel selectedHour={selectedHour} onSelectHour={setSelectedHour} />
      </div>

      {/* ─── Forecast + Webster ──────────────────────────────────── */}
      <div className="rise rise-d-5">
        <ForecastStrip />
        <WebsterBar />
      </div>

      {/* ─── Events feeds ────────────────────────────────────────── */}
      <div
        className="rise rise-d-6"
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
          gap: 14,
        }}
      >
        <LiveEventsPanel />
        <RecentSignalPanel />
      </div>

      {/* ─── Footer credit ───────────────────────────────────────── */}
      <footer
        style={{
          marginTop: 28,
          paddingTop: 18,
          borderTop: '1px solid var(--border-soft)',
          display: 'flex',
          justifyContent: 'space-between',
          font: '500 10px var(--mono)',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
        }}
      >
        <span>traffic intel · phase-3</span>
        <span style={{ color: 'var(--fg-dim)' }}>
          rtsp · mediamtx · fastapi · sqlite · react · mcp
        </span>
        <span>amman · jordan · hackathon 2026</span>
      </footer>
    </div>
  );
}
