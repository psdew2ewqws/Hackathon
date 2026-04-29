import ngeohash from "ngeohash";

export interface LatLng {
  lat: number;
  lng: number;
}

/** Geohash precision 7 ≈ 153m × 153m cells — the cache key resolution. */
export function geohash7(p: LatLng): string {
  return ngeohash.encode(p.lat, p.lng, 7);
}

/** Geohash precision 6 ≈ 1.2km × 600m. Fallback if precision 7 hit-rate is too low. */
export function geohash6(p: LatLng): string {
  return ngeohash.encode(p.lat, p.lng, 6);
}

/** Haversine distance in metres. */
export function distanceM(a: LatLng, b: LatLng): number {
  const R = 6_371_000;
  const toRad = (x: number) => (x * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
