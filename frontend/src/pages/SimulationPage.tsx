import { useCallback, useRef, useState } from 'react';
import { OperatorTopBar } from '../components/v2/OperatorTopBar';
import { PerLaneForecastTable } from '../components/sim/PerLaneForecastTable';
import { ResultsPanel } from '../components/sim/ResultsPanel';
import { TweakPanel, type TweakState } from '../components/sim/TweakPanel';
import { sendConfig, useMovsimMetrics } from '../lib/movsimBridge';
import type { Approach } from '../api/types';

const INITIAL_STATE: TweakState = {
  signal: { NS_green_s: 35, E_green_s: 35, W_green_s: 35, yellow_s: 3, all_red_s: 2 },
  demand: { N: 1, S: 1, E: 1, W: 1 },
  closures: { N: false, S: false, E: false, W: false },
  time_lapse: 4,
};

export function SimulationPage() {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [state, setState] = useState<TweakState>(INITIAL_STATE);
  const { latest, history, ready } = useMovsimMetrics(iframeRef);

  const apply = useCallback(() => {
    sendConfig(iframeRef.current, {
      signal: state.signal,
      demand_multiplier: state.demand,
      lane_closures: state.closures,
      time_lapse: state.time_lapse,
    });
  }, [state]);

  const onIframeLoad = useCallback(() => {
    // Push the current tweak state once the iframe has booted so the sim
    // doesn't sit at its hardcoded defaults.
    setTimeout(apply, 800);
  }, [apply]);

  const toggleClosure = (a: Approach) =>
    setState((s) => ({ ...s, closures: { ...s.closures, [a]: !s.closures[a] } }));

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
          gridTemplateColumns: 'minmax(320px, 0.85fr) minmax(0, 2fr) minmax(280px, 0.85fr)',
          gridTemplateRows: 'auto auto',
          gap: 12,
          gridTemplateAreas: `
            "tweak  sim     forecast"
            "tweak  results forecast"
          `,
        }}
      >
        <div style={{ gridArea: 'tweak', minWidth: 0 }}>
          <TweakPanel value={state} onChange={setState} onApply={apply} />
        </div>

        <div
          style={{
            gridArea: 'sim',
            minWidth: 0,
            background: 'var(--surface-2)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--r-md)',
            padding: 10,
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
              padding: '4px 6px',
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
              what-if simulation · IDM
            </span>
            <span
              style={{
                font: '500 10px var(--mono)',
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--fg-faint)',
              }}
            >
              vendored from movsim/traffic-simulation-de · GPL-3
            </span>
          </div>
          <div
            style={{
              flex: 1,
              minHeight: 520,
              borderRadius: 6,
              overflow: 'hidden',
              border: '1px solid var(--border-soft)',
            }}
          >
            <iframe
              ref={iframeRef}
              src="/app/movsim/"
              title="movsim what-if simulation"
              onLoad={onIframeLoad}
              style={{
                width: '100%',
                height: '100%',
                minHeight: 520,
                border: 'none',
                display: 'block',
                background: '#14171d',
              }}
            />
          </div>
        </div>

        <div style={{ gridArea: 'forecast', minWidth: 0 }}>
          <PerLaneForecastTable
            closures={state.closures}
            onToggleClosure={toggleClosure}
          />
        </div>

        <div style={{ gridArea: 'results', minWidth: 0 }}>
          <ResultsPanel latest={latest} history={history} ready={ready} />
        </div>
      </main>
    </div>
  );
}
