// Amman time utilities. Jordan is UTC+3 year-round (no DST since 2022).
const AMMAN_OFFSET_MIN = 3 * 60;

/** Day-of-week bucket: 0 = weekday (Sun-Thu), 1 = Friday, 2 = Saturday. */
export function dowBucket(d: Date): 0 | 1 | 2 {
  const dow = ammanLocalDow(d);
  if (dow === 5) return 1;
  if (dow === 6) return 2;
  return 0;
}

/** 5-minute bucket of the day in Amman local time, 0..287. */
export function todBucket5min(d: Date): number {
  const local = toAmmanLocal(d);
  return local.getUTCHours() * 12 + Math.floor(local.getUTCMinutes() / 5);
}

export function toAmmanLocal(d: Date): Date {
  return new Date(d.getTime() + AMMAN_OFFSET_MIN * 60 * 1000);
}

function ammanLocalDow(d: Date): number {
  return toAmmanLocal(d).getUTCDay();
}

/**
 * Special-day flag: Ramadan, public holidays, school summer break.
 * v0 returns false for everything; we'll wire up a calendar table later.
 */
export function isSpecialDay(_d: Date): boolean {
  return false;
}

/** Generate departure-time slots between [start, end] at the given step. */
export function enumerateSlots(start: Date, end: Date, stepMinutes: number): Date[] {
  const out: Date[] = [];
  const stepMs = stepMinutes * 60_000;
  for (let t = start.getTime(); t <= end.getTime(); t += stepMs) {
    out.push(new Date(t));
  }
  return out;
}
