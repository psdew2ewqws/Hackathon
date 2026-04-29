/** Format a Date as "YYYY-MM-DDTHH:MM" in *local* time — the value an HTML
 *  datetime-local input expects, and the format `new Date(s)` parses as local. */
export function toLocalDateTimeString(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** Round to the next 5-minute boundary (so chips give clean times). */
export function roundUpTo5Min(d: Date): Date {
  const ms = 5 * 60_000;
  return new Date(Math.ceil(d.getTime() / ms) * ms);
}

/** Build a Date for "tomorrow at HH:00" in local time. */
export function tomorrowAt(hour: number): Date {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(hour, 0, 0, 0);
  return d;
}

export interface RelativeText {
  text: string;
  tone: "good" | "tight" | "bad" | "neutral";
}

export function formatRelative(target: Date): RelativeText {
  const ms = target.getTime() - Date.now();
  if (ms < -60_000) {
    return { text: `${Math.round(-ms / 60_000)} min ago`, tone: "bad" };
  }
  if (ms < 5 * 60_000) {
    return { text: "less than 5 min away — too tight to plan", tone: "tight" };
  }
  const totalMin = Math.round(ms / 60_000);
  if (totalMin < 60) {
    return { text: `arriving in ${totalMin} min`, tone: totalMin < 15 ? "tight" : "good" };
  }
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  const days = Math.floor(h / 24);
  if (days >= 1) {
    return { text: `arriving in ${days}d ${h - days * 24}h`, tone: "good" };
  }
  return { text: `arriving in ${h}h ${m}m`, tone: "good" };
}
