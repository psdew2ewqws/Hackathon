import { config } from "../config.js";
import { geohash7, type LatLng } from "../lib/geo.js";
import { dowBucket, isSpecialDay, todBucket5min } from "../lib/time.js";
import { logObservation } from "./observationLog.js";

const ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes";

export interface RouteRequest {
  origin: LatLng;
  dest: LatLng;
  /** Departure time as a Date. Must be in the future for traffic-aware predictions. */
  departure: Date;
  userId?: string;
}

export interface RouteResult {
  durationSec: number;
  distanceM: number;
  source: "routes_api_v2";
}

/** Routes API v2: TRAFFIC_AWARE_OPTIMAL respects future departure_time predictions. */
export async function computeRoute(req: RouteRequest): Promise<RouteResult> {
  const body = {
    origin: { location: { latLng: { latitude: req.origin.lat, longitude: req.origin.lng } } },
    destination: { location: { latLng: { latitude: req.dest.lat, longitude: req.dest.lng } } },
    travelMode: "DRIVE",
    routingPreference: "TRAFFIC_AWARE_OPTIMAL",
    departureTime: req.departure.toISOString(),
    computeAlternativeRoutes: false,
    units: "METRIC",
  };

  const res = await fetch(ROUTES_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
      "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Routes API ${res.status}: ${text}`);
  }

  const json = (await res.json()) as {
    routes?: Array<{ duration?: string; distanceMeters?: number }>;
  };
  const route = json.routes?.[0];
  if (!route?.duration) throw new Error("Routes API returned no route");

  // Duration comes back as e.g. "1234s"
  const durationSec = parseInt(route.duration.replace("s", ""), 10);
  const distanceM = route.distanceMeters ?? 0;

  await logObservation({
    observed_at: new Date().toISOString(),
    origin: req.origin,
    dest: req.dest,
    origin_h7: geohash7(req.origin),
    dest_h7: geohash7(req.dest),
    departure_ts: req.departure.toISOString(),
    duration_sec: durationSec,
    distance_m: distanceM,
    dow_bucket: dowBucket(req.departure),
    tod_bucket: todBucket5min(req.departure),
    special_day: isSpecialDay(req.departure),
    source: "routes_api_v2",
    user_id: req.userId,
  });

  return { durationSec, distanceM, source: "routes_api_v2" };
}
