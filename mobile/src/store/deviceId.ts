// Device ID persistence — Week 1 uses a JS Map fallback; Week 3 swaps in
// expo-secure-store. Anonymous UUID per install.

let cached: string | undefined;

export function getDeviceId(): string {
  if (cached) return cached;
  cached = (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).toString();
  return cached;
}
