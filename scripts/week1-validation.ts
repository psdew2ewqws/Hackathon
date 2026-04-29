/**
 * Week 1 validation experiment.
 *
 * Goal: verify that Google Routes API's future-departure predictions are
 * accurate enough for Amman. Plan §Verification, Risk #1.
 *
 * Run this the night before. Then drive each corridor at the queried time
 * and record actual durations in the *_actuals.csv file.
 *
 * Pass criterion (5-day average): mean absolute error < 25%, max error < 40%.
 *
 * Usage:
 *   cd scripts && npm run validate:week1
 */

import { writeFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";

const API_KEY = process.env.GOOGLE_MAPS_API_KEY;
if (!API_KEY) {
  console.error("Set GOOGLE_MAPS_API_KEY in /home/admin1/9xAI21/9xAI-Taregak/.env");
  process.exit(1);
}

interface LatLng {
  lat: number;
  lng: number;
}

interface Corridor {
  name: string;
  origin: LatLng;
  dest: LatLng;
}

// Approximate coordinates — adjust to match the exact start/end you'll drive.
const CORRIDORS: Corridor[] = [
  {
    name: "Abdoun → University of Jordan",
    origin: { lat: 31.945, lng: 35.880 },
    dest: { lat: 31.987, lng: 35.872 },
  },
  {
    name: "7th Circle → Sweifieh",
    origin: { lat: 31.957, lng: 35.854 },
    dest: { lat: 31.937, lng: 35.860 },
  },
  {
    name: "Tabarbour → Downtown",
    origin: { lat: 32.022, lng: 35.927 },
    dest: { lat: 31.951, lng: 35.923 },
  },
];

const SLOTS_LOCAL = ["07:00", "07:30", "08:00"];

function nextWeekdayAt(hhmm: string): Date {
  const [h, m] = hhmm.split(":").map((v) => parseInt(v, 10)) as [number, number];
  // Build tomorrow at the local Amman time. UTC = local - 3.
  const now = new Date();
  const target = new Date(now);
  target.setUTCDate(now.getUTCDate() + 1);
  target.setUTCHours(h - 3, m, 0, 0);
  // If tomorrow is Friday or Saturday in Jordan, advance to Sunday for weekday traffic
  const ammanLocal = new Date(target.getTime() + 3 * 60 * 60_000);
  const dow = ammanLocal.getUTCDay(); // 5=Fri, 6=Sat
  if (dow === 5) target.setUTCDate(target.getUTCDate() + 2);
  else if (dow === 6) target.setUTCDate(target.getUTCDate() + 1);
  return target;
}

interface Prediction {
  run_at: string;
  corridor: string;
  slot_local: string;
  departure_iso: string;
  predicted_duration_sec: number;
  predicted_distance_m: number;
}

async function predict(c: Corridor, dep: Date): Promise<{ durationSec: number; distanceM: number }> {
  const res = await fetch("https://routes.googleapis.com/directions/v2:computeRoutes", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Goog-Api-Key": API_KEY!,
      "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
    },
    body: JSON.stringify({
      origin: { location: { latLng: { latitude: c.origin.lat, longitude: c.origin.lng } } },
      destination: { location: { latLng: { latitude: c.dest.lat, longitude: c.dest.lng } } },
      travelMode: "DRIVE",
      routingPreference: "TRAFFIC_AWARE_OPTIMAL",
      departureTime: dep.toISOString(),
      units: "METRIC",
    }),
  });
  if (!res.ok) throw new Error(`Routes API ${res.status}: ${await res.text()}`);
  const json = (await res.json()) as { routes?: Array<{ duration: string; distanceMeters: number }> };
  const route = json.routes?.[0];
  if (!route) throw new Error("Routes API returned no route");
  return {
    durationSec: parseInt(route.duration.replace("s", ""), 10),
    distanceM: route.distanceMeters,
  };
}

const main = async () => {
  const now = new Date();
  const predictions: Prediction[] = [];

  for (const corridor of CORRIDORS) {
    for (const slot of SLOTS_LOCAL) {
      const dep = nextWeekdayAt(slot);
      const r = await predict(corridor, dep);
      predictions.push({
        run_at: now.toISOString(),
        corridor: corridor.name,
        slot_local: slot,
        departure_iso: dep.toISOString(),
        predicted_duration_sec: r.durationSec,
        predicted_distance_m: r.distanceM,
      });
      console.log(
        `${corridor.name} @ ${slot} → ${Math.round(r.durationSec / 60)} min (${(r.distanceM / 1000).toFixed(1)} km)`,
      );
    }
  }

  const ymd = now.toISOString().slice(0, 10);
  const predictionsPath = `data/week1/${ymd}_predictions.csv`;
  const actualsPath = `data/week1/${ymd}_actuals.csv`;
  await mkdir(dirname(predictionsPath), { recursive: true });

  const header = "run_at,corridor,slot_local,departure_iso,predicted_duration_sec,predicted_distance_m";
  const rows = predictions.map(
    (p) =>
      `${p.run_at},"${p.corridor}",${p.slot_local},${p.departure_iso},${p.predicted_duration_sec},${p.predicted_distance_m}`,
  );
  await writeFile(predictionsPath, [header, ...rows].join("\n") + "\n", "utf8");

  const actualsHeader =
    "corridor,slot_local,actual_departure_iso,actual_duration_sec,notes";
  const actualsTemplate = predictions.map(
    (p) => `"${p.corridor}",${p.slot_local},,,`,
  );
  await writeFile(actualsPath, [actualsHeader, ...actualsTemplate].join("\n") + "\n", "utf8");

  console.log(`\nWrote ${predictionsPath}`);
  console.log(`Wrote ${actualsPath} — fill in actual_duration_sec after driving each corridor.`);
  console.log(`\nAfter 5 days of data: run scripts/week1-summary.ts (TODO) to compute MAE.`);
};

await main();
