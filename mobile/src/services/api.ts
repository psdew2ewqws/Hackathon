export const BASE = process.env.EXPO_PUBLIC_API_BASE ?? "http://localhost:4000";

export interface LatLng {
  lat: number;
  lng: number;
}

export interface Prediction {
  placeId: string;
  text: string;
  mainText: string;
  secondaryText?: string;
}

export async function placesAutocomplete(q: string, sessionToken: string): Promise<Prediction[]> {
  const url = new URL(`${BASE}/v1/places/autocomplete`);
  url.searchParams.set("q", q);
  url.searchParams.set("sessionToken", sessionToken);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`autocomplete ${res.status}`);
  const json = (await res.json()) as { predictions: Prediction[] };
  return json.predictions;
}

export interface PlaceDetails {
  placeId: string;
  name: string;
  formattedAddress?: string;
  location: LatLng;
}

export async function placeDetails(placeId: string, sessionToken: string): Promise<PlaceDetails> {
  const url = new URL(`${BASE}/v1/places/details`);
  url.searchParams.set("placeId", placeId);
  url.searchParams.set("sessionToken", sessionToken);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`details ${res.status}`);
  return (await res.json()) as PlaceDetails;
}

export interface AppConfig {
  googleMapsBrowserKey: string;
  ammanCenter: LatLng;
  defaultZoom: number;
}

export async function fetchConfig(): Promise<AppConfig> {
  const res = await fetch(`${BASE}/v1/config`);
  if (!res.ok) throw new Error(`config ${res.status}`);
  return (await res.json()) as AppConfig;
}

export function staticMapUrl(origin: LatLng, dest: LatLng, width = 640, height = 320): string {
  const url = new URL(`${BASE}/v1/static-map`);
  url.searchParams.set("origin", `${origin.lat},${origin.lng}`);
  url.searchParams.set("dest", `${dest.lat},${dest.lng}`);
  url.searchParams.set("width", String(width));
  url.searchParams.set("height", String(height));
  return url.toString();
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
