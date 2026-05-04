/**
 * Pure-geometry helpers for the lane calibration tools.
 *
 * Shared between the dedicated /lanes page (full canvas editor) and the
 * inline LaneQuickEditor on the Live page so both produce identical
 * perspective-correct strips for the same approach geometry.
 */

export type LaneType = 'left' | 'through' | 'right' | 'shared';

export function laneTypeFor(idx: number, total: number): LaneType {
  if (total <= 2) return 'shared';
  if (idx === 0) return 'left';
  if (idx === total - 1) return 'right';
  return 'through';
}

/**
 * Equal-divide an approach polygon into N perspective-correct lane strips.
 *
 * The polygon has 4 vertices. Two of them form the stop_line edge (closer
 * to the camera in pixel space); the other two form the back edge. We
 * order back-edge vertices to match stop_line order (left↔left, right↔right),
 * then linearly interpolate N+1 points along each edge and connect adjacent
 * pairs. Strips taper naturally toward the vanishing point because the
 * polygon already encodes the perspective.
 *
 * Returns N polygons of 4 vertices each, in pixel coords.
 */
export function equalDivideApproach(
  approachPoly: number[][],
  stopLine: [number, number][],
  n: number,
): number[][][] {
  if (approachPoly.length < 4 || stopLine.length < 2 || n < 1) return [];
  const sl0 = stopLine[0];
  const sl1 = stopLine[stopLine.length - 1];
  const eq = (a: number[], b: number[]) =>
    Math.abs(a[0] - b[0]) < 1.5 && Math.abs(a[1] - b[1]) < 1.5;
  const stopIdx = approachPoly
    .map((v, i) => (eq(v, sl0) || eq(v, sl1) ? i : -1))
    .filter((i) => i >= 0);
  const backIdx = approachPoly
    .map((_, i) => i)
    .filter((i) => !stopIdx.includes(i));
  if (stopIdx.length !== 2 || backIdx.length < 2) return [];

  const s0 = approachPoly[stopIdx[0]];
  const s1 = approachPoly[stopIdx[1]];
  const ba = approachPoly[backIdx[0]];
  const bb = approachPoly[backIdx[1]];
  const dist = (a: number[], b: number[]) =>
    Math.hypot(a[0] - b[0], a[1] - b[1]);
  const orderAB = dist(s0, ba) + dist(s1, bb);
  const orderBA = dist(s0, bb) + dist(s1, ba);
  const [b0, b1] = orderAB <= orderBA ? [ba, bb] : [bb, ba];

  const lerp = (a: number[], b: number[], t: number): number[] => [
    Math.round(a[0] + (b[0] - a[0]) * t),
    Math.round(a[1] + (b[1] - a[1]) * t),
  ];
  const stops: number[][] = [];
  const backs: number[][] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    stops.push(lerp(s0, s1, t));
    backs.push(lerp(b0, b1, t));
  }
  const strips: number[][][] = [];
  for (let i = 0; i < n; i++) {
    strips.push([stops[i], stops[i + 1], backs[i + 1], backs[i]]);
  }
  return strips;
}

/**
 * Build a centerline by walking around a "ribbon" polygon and taking the
 * midpoint between vertex i and vertex (n-1-i). For polygons produced by
 * equalDivideApproach this gives a clean lane center.
 */
export function centerlineFromPolygon(poly: number[][]): number[][] {
  const n = poly.length;
  if (n < 4) {
    const cx = poly.reduce((a, [x]) => a + x, 0) / n;
    const cy = poly.reduce((a, [, y]) => a + y, 0) / n;
    return [[cx, cy]];
  }
  const half = Math.floor(n / 2);
  const out: number[][] = [];
  for (let i = 0; i < half; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[n - 1 - i];
    out.push([(x1 + x2) / 2, (y1 + y2) / 2]);
  }
  return out;
}
