const BASE = process.env.EXPO_PUBLIC_API_BASE ?? "http://localhost:4000";

export interface LatLng {
  lat: number;
  lng: number;
}

export interface PredictDepartureRequest {
  origin: LatLng;
  dest: LatLng;
  arriveBy: string; // ISO 8601
  windowMinutes?: number;
  budget?: number;
}

export interface DepartureCandidate {
  depart: string;
  arrive: string;
  durationSec: number;
}

export interface PredictDepartureResponse {
  status: "OK" | "IMPOSSIBLE";
  recommendedDeparture?: string;
  expectedArrival?: string;
  expectedDurationSec?: number;
  alternatives: DepartureCandidate[];
  earliestArrival?: string;
  apiCallsUsed: number;
  source: "live";
}

export async function predictDeparture(
  body: PredictDepartureRequest,
  deviceId: string,
): Promise<PredictDepartureResponse> {
  const res = await fetch(`${BASE}/v1/predict-departure`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Device-Id": deviceId },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`predict-departure ${res.status}: ${await res.text()}`);
  return (await res.json()) as PredictDepartureResponse;
}
