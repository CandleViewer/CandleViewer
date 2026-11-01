// Axis label text (E11-S06, README BQ-186, BQ-203): prices to the tick's precision with thousands
// separators, and zoned calendar fields from one cached `Intl.DateTimeFormat` per time zone,
// built once per chart (never per frame). Calendar maths is integer civil-date arithmetic, so a
// label costs no `Date`. DOM-free; called only when a tick set is rebuilt.

/** Decimals a step needs: 0.5 → 1, 0.01 → 2, 1 → 0 (at most 10). */
export function decimalsOf(step: number): number {
  for (let d = 0; d < 10; d += 1) {
    const s = step * 10 ** d;
    if (Math.abs(s - Math.round(s)) < 1e-7 * Math.max(1, s)) return d;
  }
  return 10;
}

/** `64050.5` at 1 decimal is "64,050.5"; a value that rounds to zero has no sign. */
export function formatNumber(v: number, decimals: number): string {
  const fixed = Math.abs(v).toFixed(decimals);
  const dot = fixed.indexOf(".");
  const int = dot < 0 ? fixed : fixed.slice(0, dot);
  const sign = v < 0 && /[1-9]/.test(fixed) ? "-" : "";
  return sign + int.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (dot < 0 ? "" : fixed.slice(dot));
}

export const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
export const DAY_MS = 86_400_000;

/** One instant's wall-clock fields in the chart's zone; weekday 0 is Monday. */
export interface Zoned {
  year: number;
  month: number;
  day: number;
  weekday: number;
  /** Days since 1970-01-01, local. */
  days: number;
  /** Milliseconds since local midnight. */
  ms: number;
}

export const createZoned = (): Zoned => ({
  year: 1970,
  month: 1,
  day: 1,
  weekday: 3,
  days: 0,
  ms: 0,
});

/** Days since 1970-01-01 to the civil date (Hinnant's algorithm, any era). */
export function civil(days: number, out: Zoned): void {
  const z = days + 719_468;
  const era = Math.floor(z / 146_097);
  const doe = z - era * 146_097;
  const leap = Math.floor(doe / 1460) - Math.floor(doe / 36_524) + Math.floor(doe / 146_096);
  const yoe = Math.floor((doe - leap) / 365);
  const y = yoe + era * 400;
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  out.day = doy - Math.floor((153 * mp + 2) / 5) + 1;
  out.month = mp < 10 ? mp + 3 : mp - 9;
  out.year = out.month <= 2 ? y + 1 : y;
  out.weekday = (((days + 3) % 7) + 7) % 7; // 1970-01-01 was a Thursday
  out.days = days;
}

/** The inverse of `civil`: days since 1970-01-01 of year / month / day. */
export function daysFrom(year: number, month: number, day: number): number {
  const y = month <= 2 ? year - 1 : year;
  const era = Math.floor(y / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (month > 2 ? month - 3 : month + 9) + 2) / 5) + day - 1;
  return era * 146_097 + yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy - 719_468;
}

const PARTS = ["year", "month", "day", "hour", "minute", "second"] as const;
const HOUR_MS = 3_600_000;
/** Direct-mapped offset cache slots, one UTC hour each (a power of two). */
const OFFSET_SLOTS = 1024;

/**
 * A time zone's clock (BQ-203): UTC needs no formatter; any other zone builds one, once. Offsets
 * are cached per UTC hour: a new hour costs two `formatToParts` calls (its first and last second;
 * equal offsets mean no transition inside it), a cached one none, so a pan frame allocates
 * nothing. An hour holding a transition is never cached and is answered exactly per second.
 */
export class ZoneClock {
  readonly timeZone: string;
  private readonly fmt: Intl.DateTimeFormat | null;
  private readonly f = new Float64Array(PARTS.length);
  private readonly hours = new Float64Array(OFFSET_SLOTS).fill(Number.NaN);
  private readonly offsets = new Float64Array(OFFSET_SLOTS);

  constructor(timeZone = "UTC") {
    let fmt: Intl.DateTimeFormat | null = null;
    if (timeZone !== "UTC") {
      try {
        const n = "numeric";
        const o = { year: n, month: n, day: n, hour: n, minute: n, second: n } as const;
        fmt = new Intl.DateTimeFormat("en-US", { timeZone, hourCycle: "h23", ...o });
      } catch {
        fmt = null; // an unknown zone falls back to UTC rather than failing the chart
      }
    }
    this.fmt = fmt;
    this.timeZone = fmt === null ? "UTC" : timeZone;
  }

  /** The zone's offset from UTC at UTC ms `t`, in ms. */
  offset(t: number): number {
    if (this.fmt === null) return 0;
    const hour = Math.floor(t / HOUR_MS);
    const slot = hour & (OFFSET_SLOTS - 1);
    if (this.hours[slot] === hour) return this.offsets[slot] as number;
    const first = this.exact(this.fmt, hour * HOUR_MS);
    if (first !== this.exact(this.fmt, (hour + 1) * HOUR_MS - 1000)) return this.exact(this.fmt, t);
    this.hours[slot] = hour;
    this.offsets[slot] = first;
    return first;
  }

  /** The offset at the second holding UTC ms `t`, read from the formatter (it allocates). */
  private exact(fmt: Intl.DateTimeFormat, t: number): number {
    const s = Math.floor(t / 1000) * 1000;
    for (const p of fmt.formatToParts(s)) {
      const i = PARTS.indexOf(p.type as (typeof PARTS)[number]);
      if (i >= 0) this.f[i] = Number(p.value);
    }
    const f = this.f;
    const wall = (daysFrom(f[0] ?? 1970, f[1] ?? 1, f[2] ?? 1) * 24 + (f[3] ?? 0)) * 3_600_000;
    return wall + (f[4] ?? 0) * 60_000 + (f[5] ?? 0) * 1000 - s;
  }

  /** UTC ms of the local wall time `local` (one correction step: exact outside a DST jump). */
  toUtc(local: number): number {
    const guess = local - this.offset(local);
    return local - this.offset(guess);
  }

  /** The local fields of UTC ms `t`. */
  fields(t: number, out: Zoned): Zoned {
    const local = t + this.offset(t);
    const days = Math.floor(local / DAY_MS);
    civil(days, out);
    out.ms = local - days * DAY_MS;
    return out;
  }
}

const pad = (n: number): string => (n < 10 ? `0${n}` : `${n}`);

/** "13:30", with seconds when asked: from a local ms-of-day. */
export function clockText(ms: number, seconds: boolean): string {
  const s = Math.floor(ms / 1000);
  const hm = `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}`;
  return seconds ? `${hm}:${pad(s % 60)}` : hm;
}

/** "14 Oct". */
export const dateText = (z: Zoned): string => `${pad(z.day)} ${MONTHS[z.month - 1] ?? ""}`;
