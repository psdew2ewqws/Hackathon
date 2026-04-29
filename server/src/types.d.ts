declare module "ngeohash" {
  export function encode(latitude: number, longitude: number, precision?: number): string;
  export function decode(hash: string): { latitude: number; longitude: number };
  export function decode_bbox(hash: string): [number, number, number, number];
  export function neighbors(hash: string): string[];
  export function bboxes(
    minLat: number,
    minLng: number,
    maxLat: number,
    maxLng: number,
    precision?: number,
  ): string[];
}
