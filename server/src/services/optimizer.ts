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
const PHI = (1 + Math.sqrt(5)) / 2;

export async function findOptimalDeparture(req: OptimizeRequest): Promise<OptimizeResult> {
  const windowEnd = addMinutes(req.arriveBy, -5);
  const windowStart = addMinutes(req.arriveBy, -req.windowMinutes);

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

  // Pick the latest feasible coarse departure as the seed for refinement
  const seed = feasible.reduce((best, c) => (c.depart > best.depart ? c : best));

  // Golden-section refinement around the seed at 1-min granularity
  let lo = addMinutes(seed.depart, -REFINE_RADIUS_MIN);
  let hi = addMinutes(seed.depart, REFINE_RADIUS_MIN);
  if (lo < windowStart) lo = windowStart;
  if (hi > windowEnd) hi = windowEnd;

  let best = seed;
  // Run a few golden-section iterations within remaining budget
  while (calls < req.budget && minutesBetween(lo, hi) > 1) {
    const m1 = addMinutes(hi, -minutesBetween(lo, hi) / PHI);
    const m2 = addMinutes(lo, minutesBetween(lo, hi) / PHI);
    const c1 = await sample(roundToMinute(m1));
    const c2 = await sample(roundToMinute(m2));
    if (!c1 || !c2) break;
    if (c1.arrive <= req.arriveBy && c1.depart >= best.depart) best = c1;
    if (c2.arrive <= req.arriveBy && c2.depart >= best.depart) best = c2;
    if (c1.durationSec < c2.durationSec) hi = m2;
    else lo = m1;
  }

  const alternatives = [...coarse]
    .sort((a, b) => a.depart.getTime() - b.depart.getTime())
    .slice(0, 5);

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

function minutesBetween(a: Date, b: Date): number {
  return (b.getTime() - a.getTime()) / 60_000;
}

function roundToMinute(d: Date): Date {
  return new Date(Math.round(d.getTime() / 60_000) * 60_000);
}
