import { useEffect, useState } from 'react';
import { getSimulationSeed } from '../../api/client';
import {
  APPROACHES,
  APPROACH_COLOR,
  type Approach,
  type SimulationSeed,
} from '../../api/types';
import type {
  SimDemandMultiplier,
  SimLaneClosures,
  SimSignal,
} from '../../lib/movsimBridge';

const DEFAULT_SIGNAL: SimSignal = {
  NS_green_s: 35,
  E_green_s: 35,
  W_green_s: 35,
  yellow_s: 3,
  all_red_s: 2,
};

const DEFAULT_DEMAND: SimDemandMultiplier = { N: 1, S: 1, E: 1, W: 1 };
const DEFAULT_CLOSURES: SimLaneClosures = { N: false, S: false, E: false, W: false };
const DEFAULT_TIME_LAPSE = 4;

export interface TweakState {
  signal: SimSignal;
  demand: SimDemandMultiplier;
  closures: SimLaneClosures;
  time_lapse: number;
}

interface Props {
  value: TweakState;
  onChange: (next: TweakState) => void;
  onApply: () => void;
}

export function TweakPanel({ value, onChange, onApply }: Props) {
  const [seed, setSeed] = useState<SimulationSeed | null>(null);
  const [seedErr, setSeedErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getSimulationSeed()
      .then((s) => alive && setSeed(s))
      .catch((e) => alive && setSeedErr((e as Error).message));
    return () => {
      alive = false;
    };
  }, []);

  const set = <K extends keyof TweakState>(k: K, v: TweakState[K]) =>
    onChange({ ...value, [k]: v });

  const seedFromForecast = () => {
    if (!seed) return;
    // Use the +0min (now) per-approach forecast as the demand baseline,
    // expressed as a multiplier of the simulator's default flow (we treat
    // 30 veh/15min ≈ 1.0× as a sane baseline for the stylised 4-way).
    const baseline = 30;
    const fc = seed.forecast_per_approach;
    const next: SimDemandMultiplier = {
      N: clamp(fc.N.y_now / baseline, 0.4, 2.0),
      S: clamp(fc.S.y_now / baseline, 0.4, 2.0),
      E: clamp(fc.E.y_now / baseline, 0.4, 2.0),
      W: clamp(fc.W.y_now / baseline, 0.4, 2.0),
    };
    onChange({ ...value, demand: next });
  };

  const seedFromWebster = () => {
    if (!seed?.signal?.current_plan) return;
    const p = seed.signal.current_plan;
    const next: SimSignal = {
      NS_green_s: p.NS_green ?? value.signal.NS_green_s,
      E_green_s: p.E_green ?? p.EW_green ?? value.signal.E_green_s,
      W_green_s: p.W_green ?? p.EW_green ?? value.signal.W_green_s,
      yellow_s: p.yellow ?? value.signal.yellow_s,
      all_red_s: p.all_red ?? value.signal.all_red_s,
    };
    onChange({ ...value, signal: next });
  };

  const reset = () => {
    onChange({
      signal: DEFAULT_SIGNAL,
      demand: DEFAULT_DEMAND,
      closures: DEFAULT_CLOSURES,
      time_lapse: DEFAULT_TIME_LAPSE,
    });
  };

  const cycle =
    value.signal.NS_green_s +
    value.signal.E_green_s +
    value.signal.W_green_s +
    3 * (value.signal.yellow_s + value.signal.all_red_s);

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
      }}
    >
      <PanelHeader title="Tweak Panel" sub={`cycle ${cycle}s · 3-phase`} />

      {/* SIGNAL TIMING */}
      <Section label="Signal split">
        <Slider
          label="NS green"
          unit="s"
          min={5}
          max={60}
          value={value.signal.NS_green_s}
          onChange={(v) => set('signal', { ...value.signal, NS_green_s: v })}
          tone="#6FA8D6"
        />
        <Slider
          label="E green"
          unit="s"
          min={5}
          max={60}
          value={value.signal.E_green_s}
          onChange={(v) => set('signal', { ...value.signal, E_green_s: v })}
          tone="#7FA889"
        />
        <Slider
          label="W green"
          unit="s"
          min={5}
          max={60}
          value={value.signal.W_green_s}
          onChange={(v) => set('signal', { ...value.signal, W_green_s: v })}
          tone="#C583C5"
        />
        <Slider
          label="yellow"
          unit="s"
          min={1}
          max={6}
          value={value.signal.yellow_s}
          onChange={(v) => set('signal', { ...value.signal, yellow_s: v })}
          tone="var(--warn)"
        />
        <Slider
          label="all-red"
          unit="s"
          min={0}
          max={5}
          value={value.signal.all_red_s}
          onChange={(v) => set('signal', { ...value.signal, all_red_s: v })}
          tone="var(--bad)"
        />
        <button
          type="button"
          onClick={seedFromWebster}
          disabled={!seed}
          style={ghostBtn}
        >
          ← seed from Webster (current plan)
        </button>
      </Section>

      {/* DEMAND */}
      <Section label="Arrival rate (multiplier)">
        {APPROACHES.map((a) => (
          <Slider
            key={a}
            label={a}
            unit="×"
            min={0.4}
            max={2.0}
            step={0.05}
            value={value.demand[a as Approach]}
            onChange={(v) => set('demand', { ...value.demand, [a]: v })}
            tone={APPROACH_COLOR[a as Approach]}
            decimals={2}
          />
        ))}
        <button
          type="button"
          onClick={seedFromForecast}
          disabled={!seed?.forecast_available}
          style={ghostBtn}
          title={
            seed?.forecast_available
              ? 'Set demand from current LightGBM y_now'
              : 'Forecast unavailable'
          }
        >
          ← seed from LightGBM forecast (now)
        </button>
        {seedErr && (
          <div style={{ font: '500 10px var(--mono)', color: 'var(--bad)' }}>
            {seedErr}
          </div>
        )}
      </Section>

      {/* CLOSURES */}
      <Section label="Lane closures">
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 6,
          }}
        >
          {APPROACHES.map((a) => {
            const on = value.closures[a as Approach];
            return (
              <button
                key={a}
                type="button"
                onClick={() =>
                  set('closures', { ...value.closures, [a]: !on })
                }
                style={{
                  font: '600 11px var(--mono)',
                  padding: '6px 0',
                  border: '1px solid',
                  borderColor: on ? 'var(--bad)' : 'var(--border-soft)',
                  background: on ? 'rgba(255, 130, 102, 0.12)' : 'var(--surface)',
                  color: on ? 'var(--bad)' : 'var(--fg-dim)',
                  borderRadius: 5,
                  cursor: 'pointer',
                  letterSpacing: '0.04em',
                }}
              >
                {a} {on ? 'CLOSED' : 'open'}
              </button>
            );
          })}
        </div>
      </Section>

      {/* TIME LAPSE */}
      <Section label="Time lapse">
        <Slider
          label="speed"
          unit="×"
          min={1}
          max={10}
          value={value.time_lapse}
          onChange={(v) => set('time_lapse', v)}
          tone="var(--accent)"
        />
      </Section>

      {/* ACTIONS */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <button type="button" onClick={onApply} style={primaryBtn}>
          Apply to sim
        </button>
        <button type="button" onClick={reset} style={ghostBtn}>
          Reset
        </button>
      </div>
    </div>
  );
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function PanelHeader({ title, sub }: { title: string; sub: string }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
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
        {title}
      </span>
      <span
        style={{
          font: '500 10px var(--mono)',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--fg-faint)',
        }}
      >
        {sub}
      </span>
    </div>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div
        style={{
          font: '700 9px var(--mono)',
          letterSpacing: '0.2em',
          textTransform: 'uppercase',
          color: 'var(--accent)',
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function Slider({
  label,
  unit,
  min,
  max,
  step,
  value,
  onChange,
  tone,
  decimals,
}: {
  label: string;
  unit: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (v: number) => void;
  tone: string;
  decimals?: number;
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '54px 1fr 56px',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span style={{ font: '600 11px var(--mono)', color: tone }}>{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step ?? 1}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ accentColor: tone, width: '100%' }}
      />
      <span
        className="tabular"
        style={{
          font: '600 11px var(--mono)',
          color: 'var(--fg)',
          textAlign: 'right',
          letterSpacing: '-0.01em',
        }}
      >
        {value.toFixed(decimals ?? 0)}
        <span style={{ color: 'var(--fg-faint)', marginLeft: 2 }}>{unit}</span>
      </span>
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  font: '600 11px var(--mono)',
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  padding: '8px 14px',
  borderRadius: 6,
  background: 'var(--accent)',
  color: '#0a0a0a',
  border: '1px solid var(--accent)',
  cursor: 'pointer',
};

const ghostBtn: React.CSSProperties = {
  font: '600 11px var(--mono)',
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  padding: '7px 14px',
  borderRadius: 6,
  background: 'transparent',
  color: 'var(--fg-dim)',
  border: '1px solid var(--border)',
  cursor: 'pointer',
};
