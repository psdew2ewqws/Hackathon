import { useEffect, useState } from 'react';
import { getRecommendation } from '../api/client';
import type {
  PlanComparison,
  RecommendationResponse,
} from '../api/types';
import { StatBlock } from '../components/StatBlock';

export function SignalPage() {
  const [rec, setRec] = useState<RecommendationResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let t: number;
    const tick = async () => {
      try {
        const r = await getRecommendation();
        if (!alive) return;
        setRec(r);
        setErr(null);
      } catch (e) {
        if (alive) setErr(String((e as Error).message ?? e));
      }
      if (alive) t = window.setTimeout(tick, 2000);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  if (err && !rec) {
    return <div style={{ padding: 18, color: '#fecaca' }}>Error: {err}</div>;
  }
  if (!rec) {
    return <div style={{ padding: 18, opacity: 0.7 }}>Loading…</div>;
  }

  const cmp = rec.recommendation?.comparison;
  const phases = rec.recommendation?.phases;
  if (!cmp || !phases) {
    return (
      <div style={{ padding: 18, opacity: 0.7 }}>
        Awaiting recommendation payload…
      </div>
    );
  }

  const delta = cmp.delay_reduction_pct ?? 0;
  const deltaColor = delta >= 0 ? '#66ff88' : '#ff7a7a';

  return (
    <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Signal plan · two-phase Webster</h2>
        <span
          style={{
            padding: '3px 10px',
            borderRadius: 999,
            background: '#1e2630',
            color: deltaColor,
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {delta >= 0 ? '−' : '+'}
          {Math.abs(delta).toFixed(1)}% delay
        </span>
        <span style={{ opacity: 0.65, fontSize: 13 }}>
          hour {rec.local_hour?.toFixed(1)}
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, minmax(280px, 1fr))',
          gap: 14,
        }}
      >
        <PlanColumn title="Current (field)" plan={cmp.current} accent="#e6edf3" />
        <PlanColumn title="Recommended" plan={cmp.recommended} accent="#66ff88" />
      </div>

      <section
        style={{
          background: '#121820',
          border: '1px solid #1e2630',
          borderRadius: 10,
          padding: 14,
        }}
      >
        <h3 style={{ margin: '0 0 12px', fontSize: 13, letterSpacing: '.06em', textTransform: 'uppercase', opacity: 0.7 }}>
          Green-time comparison
        </h3>
        <BarCompare
          label="NS green"
          current={cmp.current.NS_green}
          recommended={cmp.recommended.NS_green}
        />
        <BarCompare
          label="EW green"
          current={cmp.current.EW_green ?? 0}
          recommended={cmp.recommended.EW_green ?? 0}
        />
        <div style={{ marginTop: 14, fontSize: 13, opacity: 0.85 }}>
          Y = {rec.recommendation.flow_ratio_total.toFixed(2)}
          &nbsp;·&nbsp; y<sub>NS</sub> = {phases.NS.flow_ratio.toFixed(2)}
          &nbsp;·&nbsp; y<sub>EW</sub> = {phases.EW.flow_ratio.toFixed(2)}
          &nbsp;·&nbsp; lost time {rec.recommendation.lost_time_seconds.toFixed(1)}s
        </div>
      </section>
    </div>
  );
}

function PlanColumn({
  title,
  plan,
  accent,
}: {
  title: string;
  plan: PlanComparison;
  accent: string;
}) {
  return (
    <div
      style={{
        background: '#121820',
        border: '1px solid #1e2630',
        borderRadius: 10,
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: accent, marginBottom: 2 }}>
        {title}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        <StatBlock label="NS green" value={`${plan.NS_green.toFixed(1)}s`} accent={accent} />
        <StatBlock label="EW green" value={`${(plan.EW_green ?? 0).toFixed(1)}s`} accent={accent} />
        <StatBlock label="Yellow" value={`${plan.yellow.toFixed(1)}s`} />
        <StatBlock label="All-red" value={`${plan.all_red.toFixed(1)}s`} />
        <StatBlock label="Cycle" value={`${plan.cycle_seconds.toFixed(1)}s`} />
        <StatBlock
          label="Delay s/veh"
          value={plan.uniform_delay_sec_per_veh.toFixed(2)}
        />
      </div>
    </div>
  );
}

function BarCompare({
  label,
  current,
  recommended,
}: {
  label: string;
  current: number;
  recommended: number;
}) {
  const max = Math.max(current, recommended, 1);
  const pct = (v: number) => `${(v / max) * 100}%`;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 6 }}>{label}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <Bar caption={`current ${current.toFixed(1)}s`} width={pct(current)} color="#4aaccb" />
        <Bar caption={`recommended ${recommended.toFixed(1)}s`} width={pct(recommended)} color="#66ff88" />
      </div>
    </div>
  );
}

function Bar({
  caption,
  width,
  color,
}: {
  caption: string;
  width: string;
  color: string;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div
        style={{
          flex: '0 0 auto',
          height: 18,
          width,
          background: color,
          borderRadius: 4,
          minWidth: 4,
          transition: 'width .3s ease',
        }}
      />
      <span style={{ fontSize: 12, opacity: 0.8 }}>{caption}</span>
    </div>
  );
}
