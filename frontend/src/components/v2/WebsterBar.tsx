import { useEffect, useState } from 'react';
import { getRecommendation } from '../../api/client';
import type { PlanComparison, RecommendationResponse } from '../../api/types';

interface Slice {
  label: string;
  seconds: number;
  color: string;
}

const PHASE_COLOR = {
  NS: '#6FA8D6',
  E: '#7FA889',
  W: '#C583C5',
  EW: '#E8B464',
  yellow: '#3a3a3a',
  all_red: '#1f1f1f',
} as const;

function planSlices(p: PlanComparison): Slice[] {
  const yellow = p.yellow ?? 0;
  const allRed = p.all_red ?? 0;
  const slices: Slice[] = [];
  if (p.E_green != null && p.W_green != null) {
    slices.push({ label: 'NS', seconds: p.NS_green, color: PHASE_COLOR.NS });
    slices.push({ label: 'Y', seconds: yellow, color: PHASE_COLOR.yellow });
    slices.push({ label: 'AR', seconds: allRed, color: PHASE_COLOR.all_red });
    slices.push({ label: 'E', seconds: p.E_green, color: PHASE_COLOR.E });
    slices.push({ label: 'Y', seconds: yellow, color: PHASE_COLOR.yellow });
    slices.push({ label: 'AR', seconds: allRed, color: PHASE_COLOR.all_red });
    slices.push({ label: 'W', seconds: p.W_green, color: PHASE_COLOR.W });
    slices.push({ label: 'Y', seconds: yellow, color: PHASE_COLOR.yellow });
    slices.push({ label: 'AR', seconds: allRed, color: PHASE_COLOR.all_red });
  } else {
    slices.push({ label: 'NS', seconds: p.NS_green, color: PHASE_COLOR.NS });
    slices.push({ label: 'Y', seconds: yellow, color: PHASE_COLOR.yellow });
    slices.push({ label: 'AR', seconds: allRed, color: PHASE_COLOR.all_red });
    slices.push({ label: 'EW', seconds: p.EW_green ?? 0, color: PHASE_COLOR.EW });
    slices.push({ label: 'Y', seconds: yellow, color: PHASE_COLOR.yellow });
    slices.push({ label: 'AR', seconds: allRed, color: PHASE_COLOR.all_red });
  }
  return slices.filter((s) => s.seconds > 0);
}

function PlanRow({ title, plan, totalForScale }: { title: string; plan: PlanComparison; totalForScale: number }) {
  const slices = planSlices(plan);
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 4,
        }}
      >
        <span
          style={{
            font: '500 11px var(--mono)',
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            color: 'var(--fg-dim)',
          }}
        >
          {title}
        </span>
        <span
          style={{
            font: '500 11px var(--mono)',
            color: 'var(--fg-faint)',
          }}
        >
          cycle {plan.cycle_seconds.toFixed(0)}s · delay {plan.uniform_delay_sec_per_veh.toFixed(1)} s/veh
        </span>
      </div>
      <div
        style={{
          display: 'flex',
          height: 22,
          background: 'var(--surface)',
          borderRadius: 4,
          overflow: 'hidden',
          border: '1px solid var(--border-soft)',
        }}
      >
        {slices.map((s, i) => (
          <div
            key={i}
            style={{
              width: `${(s.seconds / totalForScale) * 100}%`,
              background: s.color,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              font: '600 10px var(--mono)',
              color: 'rgba(0,0,0,0.7)',
            }}
            title={`${s.label} · ${s.seconds.toFixed(1)}s`}
          >
            {s.seconds >= 6 ? `${s.label} ${s.seconds.toFixed(0)}` : ''}
          </div>
        ))}
      </div>
    </div>
  );
}

export function WebsterBar() {
  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let t: number;
    const tick = async () => {
      try {
        const r = await getRecommendation();
        if (alive) {
          setData(r);
          setError(null);
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
      if (alive) t = window.setTimeout(tick, 1000);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  const cmp = data?.recommendation?.comparison;
  const totalForScale = Math.max(
    cmp?.current.cycle_seconds ?? 60,
    cmp?.recommended.cycle_seconds ?? 60,
  );
  const dr = cmp?.delay_reduction_pct;
  const drTone =
    dr == null ? 'var(--fg-faint)' : dr > 0 ? 'var(--good)' : 'var(--warn)';

  return (
    <div
      style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--r-md)',
        padding: '14px 16px',
        marginBottom: 14,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 12,
        }}
      >
        <div
          style={{
            font: '600 11px var(--mono)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--fg-dim)',
          }}
        >
          Webster recommendation · current vs optimised
        </div>
        <div
          style={{
            font: '600 12px var(--mono)',
            color: drTone,
          }}
        >
          {dr == null
            ? '—'
            : `delay ${dr >= 0 ? '↓' : '↑'} ${Math.abs(dr).toFixed(1)}%`}
          {cmp?.near_saturation && (
            <span
              style={{ marginLeft: 8, color: 'var(--warn)', fontSize: 10 }}
              title="Field plan preserved — system is near saturation"
            >
              · near-saturation
            </span>
          )}
        </div>
      </div>

      {error && (
        <div style={{ font: '500 11px var(--mono)', color: 'var(--bad)' }}>{error}</div>
      )}

      {cmp && (
        <>
          <PlanRow title="Current (field)" plan={cmp.current} totalForScale={totalForScale} />
          <PlanRow
            title="Recommended (Webster)"
            plan={cmp.recommended}
            totalForScale={totalForScale}
          />
        </>
      )}
    </div>
  );
}
