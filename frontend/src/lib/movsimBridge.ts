/**
 * Tiny helper for talking to the vendored movsim iframe at /app/movsim/.
 *
 * The vendored index.html appends an IIFE that listens for {type:'config'}
 * messages and emits {type:'metrics'} messages once per real-time second.
 * This module just wraps postMessage + addEventListener with cleanup so
 * the React layer never touches window.message handlers directly.
 */
import { useEffect, useRef, useState } from 'react';
import type { Approach } from '../api/types';

export interface SimSignal {
  NS_green_s: number;
  E_green_s: number;
  W_green_s: number;
  yellow_s: number;
  all_red_s: number;
}

export interface SimDemandMultiplier {
  N: number; S: number; E: number; W: number;
}

export interface SimLaneClosures {
  N: boolean; S: boolean; E: boolean; W: boolean;
}

export interface SimConfig {
  type: 'config';
  signal: SimSignal;
  demand_multiplier: SimDemandMultiplier;
  lane_closures: SimLaneClosures;
  time_lapse: number;
}

export interface SimMetrics {
  type: 'metrics';
  sim_time_s: number;
  avg_delay_s_per_veh: number;
  throughput_per_15min: number;
  queue_length: Record<Approach, number>;
  vehicles_active: number;
  config_in_force: SimConfig | null;
}

/** Send a config to the iframe. Idempotent — last write wins inside movsim. */
export function sendConfig(
  iframe: HTMLIFrameElement | null,
  cfg: Omit<SimConfig, 'type'>,
): void {
  if (!iframe || !iframe.contentWindow) return;
  const message: SimConfig = { type: 'config', ...cfg };
  iframe.contentWindow.postMessage(message, '*');
}

/**
 * Subscribe to {type:'metrics'} from the iframe and return:
 *   - latest:        most-recent metrics frame
 *   - history:       last `windowSize` frames (for rolling charts)
 *   - ready:         true once the iframe has emitted {type:'ready'}
 */
export function useMovsimMetrics(
  iframeRef: React.RefObject<HTMLIFrameElement | null>,
  windowSize = 300, // ~5 min at 1 Hz
): { latest: SimMetrics | null; history: SimMetrics[]; ready: boolean } {
  const [latest, setLatest] = useState<SimMetrics | null>(null);
  const [ready, setReady] = useState(false);
  const historyRef = useRef<SimMetrics[]>([]);
  const [, force] = useState(0);

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      // Only accept messages from our embedded iframe (best-effort —
      // contentWindow comparison fails cross-origin but here we're same-origin).
      if (
        iframeRef.current &&
        e.source !== null &&
        e.source !== iframeRef.current.contentWindow
      ) {
        return;
      }
      const data = e.data as { type?: string };
      if (!data || typeof data !== 'object') return;
      if (data.type === 'ready') {
        setReady(true);
        return;
      }
      if (data.type === 'metrics') {
        const frame = data as SimMetrics;
        setLatest(frame);
        historyRef.current.push(frame);
        if (historyRef.current.length > windowSize) {
          historyRef.current.shift();
        }
        force((n) => n + 1);
      }
    }
    window.addEventListener('message', onMessage);
    return () => {
      window.removeEventListener('message', onMessage);
    };
  }, [iframeRef, windowSize]);

  return { latest, history: historyRef.current, ready };
}
