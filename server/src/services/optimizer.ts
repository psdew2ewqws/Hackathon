import { computeRoute } from "./routesClient.js";
import type { LatLng } from "../lib/geo.js";
import { enumerateSlots } from "../lib/time.js";

/**
 * Tier 2 optimizer (Week 1 build): coarse 15-min sweep + 1-min golden-section refine.
 * Tier 1 (cache lookup) and Tier 3 (full sweep when API budget exhausted)
 * land in Week 2 alongside Postgres.
 */

export interface OptimizeRequest {
  origin: LatLng;
  dest: LatLng;
  arriveBy: Date;
  windowMinutes: number; // search window
  budget: number; // hard cap on API calls
  userId?: string;
}

export interface DepartureCandidate {
  depart: Date;
  arrive: Date;
  durationSec: number;
}

export interface OptimizeResult {
  status: "OK" | "IMPOSSIBLE";
  recommendedDeparture?: Date;
  expectedArrival?: Date;
  expectedDurationSec?: number;
  alternatives: DepartureCandidate[];
  earliestArrival?: Date;
  apiCallsUsed: number;
  source: "live";
}

const COARSE_STEP_MIN = 15;
const REFINE_RADIUS_MIN = 7;
const NOW_BUFFER_MIN = 2; // Routes API rejects departure_time in the past

/**
 * Tolerance band around the fastest feasible slot. We accept any slot whose
 * duration is within (TOLERANCE_PCT) OR (TOLERANCE_BASE_SEC) of the minimum,
 * whichever is more permissive. Among acceptable slots, we pick the LATEST
 * departure — minimizing wait time at destination while still meaningfully
 * avoiding traffic spikes.
 *
 * Examples:
 *  - Sunday rush: 17 vs 22 min spread. Threshold = 20.4 min. Acceptable
 *    slots = those at ≤ 20 min. Latest acceptable ≈ 8:00. Arrive ~36 min
 *    early instead of 69.
 *  - Friday weekend: 15-16 min everywhere. All slots acceptable. Latest
 *    feasible wins (~8:30-8:44), arriving close to the deadline.
 */
const TOLERANCE_PCT = 0.20;
const TOLERANCE_BASE_SEC = 3 * 60;

function acceptableThresholdSec(minDurationSec: number): number {
  return Math.max(minDurationSec * (1 + TOLERANCE_PCT), minDurationSec + TOLERANCE_BASE_SEC);
}

export async function findOptimalDeparture(req: OptimizeRequest): Promise<OptimizeResult> {
  const earliestAllowed = new Date(Date.now() + NOW_BUFFER_MIN * 60_000);
  const windowEnd = addMinutes(req.arriveBy, -5);
  const rawWindowStart = addMinutes(req.arriveBy, -req.windowMinutes);
  const windowStart = rawWindowStart < earliestAllowed ? earliestAllowed : rawWindowStart;

  // If arriveBy is in the past (or less than 5 min away), it's not feasible
  if (windowEnd <= windowStart) {
    return {
      status: "IMPOSSIBLE",
      earliestArrival: earliestAllowed,
      alternatives: [],
      apiCallsUsed: 0,
      source: "live",
    };
  }

  let calls = 0;
  const sample = async (t: Date): Promise<DepartureCandidate | null> => {
    if (calls >= req.budget) return null;
    calls++;
    const r = await computeRoute({
      origin: req.origin,
      dest: req.dest,
      departure: t,
      userId: req.userId,
    });
    return {
      depart: t,
      arrive: new Date(t.getTime() + r.durationSec * 1000),
      durationSec: r.durationSec,
    };
  };

  // Coarse sweep
  const coarseSlots = enumerateSlots(windowStart, windowEnd, COARSE_STEP_MIN);
  const coarse: DepartureCandidate[] = [];
  for (const t of coarseSlots) {
    const c = await sample(t);
    if (c) coarse.push(c);
  }

  if (coarse.length === 0) {
    return { status: "IMPOSSIBLE", alternatives: [], apiCallsUsed: calls, source: "live" };
  }

  const feasible = coarse.filter((c) => c.arrive <= req.arriveBy);
  if (feasible.length === 0) {
    const earliest = coarse.reduce((best, c) => (c.arrive < best.arrive ? c : best));
    return {
      status: "IMPOSSIBLE",
      earliestArrival: earliest.arrive,
      alternatives: coarse,
      apiCallsUsed: calls,
      source: "live",
    };
  }

  // Compute the acceptability threshold from the coarse data.
  const minDur = Math.min(...feasible.map((c) => c.durationSec));
  const threshold = acceptableThresholdSec(minDur);
  const acceptable = feasible.filter((c) => c.durationSec <= threshold);

  // Seed = latest acceptable coarse slot (minimizes wait without hitting peak traffic).
  const seed = acceptable.reduce((best, c) => (c.depart > best.depart ? c : best));

  // Refinement: walk forward minute-by-minute from the seed, stopping when
  // duration exits the acceptable band or arrival exceeds the deadline.
  // This finds the LATEST 1-min slot that's still within the no-rush band.
  let best = seed;
  const refineCap = Math.min(addMinutes(seed.depart, REFINE_RADIUS_MIN).getTime(), windowEnd.getTime());
  for (let mins = 1; calls < req.budget; mins++) {
    const t = new Date(seed.depart.getTime() + mins * 60_000);
    if (t.getTime() > refineCap) break;
    const c = await sample(t);
    if (!c) break;
    if (c.arrive > req.arriveBy) break;
    if (c.durationSec > threshold) break;
    best = c;
  }

  // Return alternatives sorted by departure time so the UI can render a
  // departure-vs-duration curve.
  const alternatives = [...coarse]
    .sort((a, b) => a.depart.getTime() - b.depart.getTime())
    .slice(0, 8);

  return {
    status: "OK",
    recommendedDeparture: best.depart,
    expectedArrival: best.arrive,
    expectedDurationSec: best.durationSec,
    alternatives,
    apiCallsUsed: calls,
    source: "live",
  };
}

function addMinutes(d: Date, m: number): Date {
  return new Date(d.getTime() + m * 60_000);
}
