import type {
  CountsResponse,
  ForecastResponse,
  FusionResponse,
  GmapsResponse,
  HeatmapResponse,
  RecommendationResponse,
  SiteConfig,
} from './types';

// Backend origin. In dev Vite proxies /api /mjpeg /ws to :8000, so the
// default empty base keeps relative URLs and the proxy takes over.
const RAW_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
export const API_BASE = RAW_BASE.replace(/\/$/, '');

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function wsUrl(path: string): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, 'ws') + path;
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${path}`;
}

async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(apiUrl(path), { signal });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return (await r.json()) as T;
}

export const getSite = (s?: AbortSignal) =>
  getJSON<SiteConfig>('/api/site', s);

export const getCounts = (s?: AbortSignal) =>
  getJSON<CountsResponse>('/api/counts', s);

export const getFusion = (s?: AbortSignal) =>
  getJSON<FusionResponse>('/api/fusion', s);

export const getRecommendation = (s?: AbortSignal) =>
  getJSON<RecommendationResponse>('/api/recommendation', s);

export const getGmaps = (hour: number, s?: AbortSignal) =>
  getJSON<GmapsResponse>(`/api/gmaps?hour=${hour}`, s);

export const getHeatmap = (s?: AbortSignal) =>
  getJSON<HeatmapResponse>('/api/heatmap', s);

export const getForecast = (hour: number, s?: AbortSignal) =>
  getJSON<ForecastResponse>(`/api/forecast?hour=${hour}`, s);
