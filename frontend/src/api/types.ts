// Types mirroring the Wadi Saqra PoC backend (phase3-fullstack server.py).

export type Approach = 'S' | 'N' | 'E' | 'W';

export const APPROACHES: Approach[] = ['S', 'N', 'E', 'W'];

export const APPROACH_COLOR: Record<Approach, string> = {
  S: '#66ff88',
  N: '#ff7a7a',
  E: '#f5a53c',
  W: '#4aaccb', // backend literal is "#4aacceb" (9 chars) — normalise to 7-hex
};

export type CongestionLabel =
  | 'free'
  | 'light'
  | 'moderate'
  | 'heavy'
  | 'jam'
  | string;

export interface SiteConfig {
  site_id: string;
  name: string;
  lat: number;
  lng: number;
  video?: {
    captured_at_local?: string;
    captured_at_utc?: string;
    intended_local_hour?: number;
  };
  signal?: {
    mode?: string;
    current_plan?: SignalPlan;
  };
  approaches?: Record<Approach, { corridor: string; label: string }>;
}

export interface SignalPlan {
  NS_green: number;
  EW_green: number;
  yellow: number;
  all_red: number;
}

export interface CountsResponse {
  running: boolean;
  fps: number;
  frame_ts: number | null;
  bin_start_ts: number | null;
  bin_seconds: number;
  counts: Record<Approach, { in_zone: number; crossings_total: number }>;
  crossings_in_current_bin: Record<Approach, number>;
  last_error: string | null;
}

export interface GmapsRow {
  congestion_ratio: number;
  congestion_label: CongestionLabel;
  speed_kmh: number;
  static_speed_kmh: number;
  duration_s: number;
  static_duration_s: number;
  local_hour: number;
}

export interface GmapsResponse {
  local_hour: number;
  rows: Record<Approach, GmapsRow>;
}

export interface FusedRow {
  in_zone: number;
  crossings_in_bin: number;
  demand_per_min: number;
  queue: number;
  gmaps_congestion_ratio: number;
  gmaps_label: CongestionLabel;
  gmaps_speed_kmh: number;
  pressure: number;
  label: string;
}

export interface FusionResponse {
  local_hour: number;
  fused: Record<Approach, FusedRow>;
}

export interface PlanComparison {
  NS_green: number;
  EW_green: number;
  yellow: number;
  all_red: number;
  cycle_seconds: number;
  uniform_delay_sec_per_veh: number;
}

export interface Recommendation {
  mode: string;
  cycle_seconds: number;
  lost_time_seconds: number;
  flow_ratio_total: number;
  phases: {
    NS: { green_seconds: number; flow_ratio: number };
    EW: { green_seconds: number; flow_ratio: number };
  };
  comparison: {
    current: PlanComparison;
    recommended: PlanComparison;
    delay_reduction_pct: number;
  };
}

export interface RecommendationResponse {
  local_hour: number;
  signal: SiteConfig['signal'];
  fused: Record<Approach, FusedRow>;
  recommendation: Recommendation;
}

// /api/heatmap — pre-computed 24h × 4-approach grid at half-hour resolution.
export interface HeatmapCell {
  hour: number;
  pressure: number | null;
  label: CongestionLabel | null;
  gmaps_ratio: number | null;
  gmaps_label: CongestionLabel | null;
  gmaps_speed_kmh: number | null;
}

export interface HeatmapResponse {
  hours: number[];
  approaches: Approach[];
  current_hour: number;
  cells: Record<Approach, HeatmapCell[]>;
}

// /api/forecast?hour=H — scaled prediction + Webster recommendation.
export interface PredictedRow extends FusedRow {
  scale_vs_now: number;
}

export interface ForecastResponse {
  requested_hour: number;
  baseline_hour: number;
  predicted: Record<Approach, PredictedRow>;
  recommendation: Recommendation;
}
