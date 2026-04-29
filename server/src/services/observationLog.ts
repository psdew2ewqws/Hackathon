import { appendFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import type { LatLng } from "../lib/geo.js";

// Week 1: append to JSON-lines file. Week 2: replace with TimescaleDB hypertable
// (`route_observations`). The shape stays roughly the same.

const LOG_PATH = new URL("../../../data/observations.jsonl", import.meta.url).pathname;
let dirReady = false;

export interface Observation {
  observed_at: string;
  origin: LatLng;
  dest: LatLng;
  origin_h7: string;
  dest_h7: string;
  departure_ts: string;
  duration_sec: number;
  distance_m: number;
  dow_bucket: 0 | 1 | 2;
  tod_bucket: number;
  special_day: boolean;
  source: string;
  user_id?: string;
}

export async function logObservation(obs: Observation): Promise<void> {
  if (!dirReady) {
    await mkdir(dirname(LOG_PATH), { recursive: true });
    dirReady = true;
  }
  await appendFile(LOG_PATH, JSON.stringify(obs) + "\n", "utf8");
}
