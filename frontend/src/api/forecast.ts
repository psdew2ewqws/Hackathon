/**
 * Typed HTTP client for the Python viewer's forecast endpoints.
 *
 * Two JSON endpoints are consumed:
 *   GET /api/forecast                               — full-day prediction
 *   GET /api/forecast/optimize?t=HH:MM&gN=..&gS=..  — Webster/HCM evaluation
 */

export type SignalColor = 'green' | 'yellow' | 'red' | 'gray';
export type CongestionLabel =
  | 'free' | 'light' | 'heavy' | 'jam' | 'unknown';

// ── /api/forecast ─────────────────────────────────────────────────────────
export interface ForecastRow {
  approach: 'N' | 'S' | 'E' | 'W';
  time: string;              // "HH:MM"
  count: number | null;
  speed_kmh: number | null;
  ratio: number | null;
  ratio_t0?: number;
  factor?: number;
  signal: SignalColor;
  label: CongestionLabel;
  confidence: 'low' | 'medium' | 'n/a';
}

export interface Anchor {
  frames: number;
  video_fps: number;
  duration_s: number;
  per_approach_count: Record<'N' | 'S' | 'E' | 'W', number>;
}

export interface ForecastDay {
  available: boolean;
  message?: string;
  anchor?: Anchor;
  t0_hhmm?: string;
  typical_source?: string;
  slots?: string[];
  rows?: ForecastRow[];
}

// ── /api/forecast/optimize ────────────────────────────────────────────────
export type PhaseNumber = 2 | 4 | 6 | 8;

export interface EvalRow {
  approach: 'N' | 'S' | 'E' | 'W';
  phase: PhaseNumber;
  green_s: number;
  volume_vph: number;
  lanes: number;
  flow_ratio_y: number;
  capacity_vph: number;
  x: number;
  delay_s: number;
  recommendation: string;
  signal_color: SignalColor;
}

export interface EvalSummary {
  cycle_s: number;
  lost_time_s: number;
  critical_y: number;
  cycle_saturated: boolean;
  weighted_avg_delay_s: number;
  approach_worst_x: number;
}

export interface EvalPacket {
  green: Record<string, number>;   // { "2": 35, "6": 15, "4": 22, "8": 10 }
  cycle_s: number;
  critical_y: number;
  summary: EvalSummary;
  rows: EvalRow[];
}

export interface OptimizeResponse {
  available: boolean;
  message?: string;
  t?: string;
  correction?: number;
  approach_inputs?: Record<
    'N' | 'S' | 'E' | 'W',
    { volume_vph: number; lanes: number }
  >;
  current?: EvalPacket;
  webster?: EvalPacket;
  delay_reduction_pct?: number;
}

// ── Fetchers ──────────────────────────────────────────────────────────────
export async function fetchForecast(): Promise<ForecastDay> {
  const res = await fetch('/api/forecast');
  if (!res.ok) throw new Error(`forecast ${res.status}`);
  return res.json();
}

export async function fetchOptimize(
  t: string,
  greens?: Partial<Record<PhaseNumber, number>>,
): Promise<OptimizeResponse> {
  const params = new URLSearchParams({ t });
  if (greens) {
    for (const ph of [2, 4, 6, 8] as PhaseNumber[]) {
      const v = greens[ph];
      if (v !== undefined) params.set(`g${ph}`, String(Math.round(v)));
    }
  }
  const res = await fetch(`/api/forecast/optimize?${params}`);
  if (!res.ok) throw new Error(`optimize ${res.status}`);
  return res.json();
}

// ── Helpers ───────────────────────────────────────────────────────────────
export function slotToHhmm(idx: number): string {
  const h = String(Math.floor(idx / 2)).padStart(2, '0');
  const m = idx % 2 === 0 ? '00' : '30';
  return `${h}:${m}`;
}

export function hhmmToSlot(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 2 + (m >= 30 ? 1 : 0);
}

export const PHASE_NAMES: Record<PhaseNumber, string> = {
  2: 'N/S through',
  6: 'N/S left',
  4: 'E/W through',
  8: 'E/W left',
};

export const DEFAULT_PHASE_PLAN: Record<PhaseNumber, number> = {
  2: 35,
  6: 15,
  4: 22,
  8: 10,
};
