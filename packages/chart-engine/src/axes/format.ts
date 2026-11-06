// Axis label text (E11-S06, README BQ-186, BQ-203): prices to the tick's precision with thousands
// separators, and zoned calendar fields from one cached `Intl.DateTimeFormat` per time zone,
// built once per chart (never per frame). Calendar maths is integer civil-date arithmetic, so a
// label costs no `Date`. DOM-free; called only when a tick set is rebuilt.

/**
 * Decimals a step needs: 0.5 → 1, 0.01 → 2, 1 → 0, 2.5e-8 → 9 (at most 10). The tolerance is
 * relative to the scaled step, and a step that rounds to 0 never matches, so a step below 1e-7
 * still gets its digits.
 */
export function decimalsOf(step: number): number {
  if (!(Math.abs(step) > 0) || !Number.isFinite(step)) return 0; // no step: whole numbers
  for (let d = 0; d < 10; d += 1) {
    const s = Math.abs(step) * 10 ** d;
    const r = Math.round(s);
    if (r !== 0 && Math.abs(s - r) < 1e-7 * s) return d;
  }
  return 10;
}

/**
 * `64050.5` at 1 decimal is "64,050.5"; a value that rounds to zero has no sign. A non-finite
 * value is "" (never "Infinity" / "NaN": every emitted character is in F-03's set).
 */
export function formatNumber(v: number, decimals: number): string {
  if (!Number.isFinite(v)) return "";
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
const SEC = 1000;
/**
 * The probe stride while finding a run's ends. It assumes no offset changes and changes back
 * within one stride, so it must stay below tzdb's shortest stint: 6.958 days (America/Noronha,
 * Recife and Boa_Vista 2000-10-08 to 15; Asia/Gaza and Hebron 2040-10-20 to 26). Six days.
 */
const PROBE_MS = 6 * 86_400_000;
/** A run's probe stops after this many strides (about a year); a neighbouring miss extends it. */
const PROBE_STEPS = 61;
/** Runs held per zone; the run farthest from a miss is evicted (memory stays bounded). */
export const RUN_CAP = 512;
/** The ECMAScript time value bound, in ms. */
const MAX_T = 8.64e15;

/**
 * A time zone's clock (BQ-203): UTC needs no formatter; any other zone builds one, once. Offsets
 * are piecewise constant, so the clock caches constant-offset RUNS [start, end) of UTC ms, sorted:
 * a lookup tests the last-hit run, then bisects the table, and allocates nothing. A miss reads the
 * offset there, walks six days at a time to each end (stopping at a neighbouring run) and bisects
 * the last stride to the second, so `formatToParts` (which allocates) runs only while a run is
 * new: a repeated or panned pass over runs already seen reads no formatter, at any zoom.
 */
export class ZoneClock {
  readonly timeZone: string;
  /** `formatToParts` calls so far (a counter for the tests and the bench, BQ-203). */
  reads = 0;
  private readonly fmt: Intl.DateTimeFormat | null;
  private readonly f = new Float64Array(PARTS.length);
  private readonly starts: Float64Array;
  private readonly ends: Float64Array;
  private readonly offs: Float64Array;
  private n = 0;
  private last = 0;

  constructor(
    timeZone = "UTC",
    readonly cap = RUN_CAP,
  ) {
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
    const size = fmt === null ? 0 : cap; // UTC holds no runs
    this.starts = new Float64Array(size);
    this.ends = new Float64Array(size);
    this.offs = new Float64Array(size);
  }

  /** Runs held now (at most `cap`). */
  get runs(): number {
    return this.n;
  }

  /** The zone's offset from UTC at UTC ms `t`, in ms. */
  offset(t: number): number {
    if (this.fmt === null) return 0;
    const last = this.last;
    if (last < this.n && t >= (this.starts[last] as number) && t < (this.ends[last] as number)) {
      return this.offs[last] as number;
    }
    const i = this.runAt(t);
    if (i >= 0 && t < (this.ends[i] as number)) {
      this.last = i;
      return this.offs[i] as number;
    }
    return this.miss(this.fmt, t, i);
  }

  /** The last run starting at or before `t`, or -1. */
  private runAt(t: number): number {
    let lo = 0;
    let hi = this.n - 1;
    let at = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if ((this.starts[mid] as number) <= t) {
        at = mid;
        lo = mid + 1;
      } else hi = mid - 1;
    }
    return at;
  }

  /** `t` lies in the gap after run `i` (or before every run): find, store and answer its run. */
  private miss(fmt: Intl.DateTimeFormat, t: number, i: number): number {
    const s = Math.floor(t / SEC) * SEC;
    const o = this.exact(fmt, s);
    // Probes stay inside the ECMAScript time range and the gap around `t`.
    const floor = Math.max(i >= 0 ? (this.ends[i] as number) : -MAX_T, -MAX_T);
    const ceil = Math.min(i + 1 < this.n ? (this.starts[i + 1] as number) : MAX_T, MAX_T);
    // Left end: the first second of the run.
    let start = s;
    for (let k = 0; ; k += 1) {
      if (k === PROBE_STEPS) break;
      const b = Math.max(start - PROBE_MS, floor);
      if (b >= start) break;
      if (this.exact(fmt, b) !== o) {
        start = this.bisect(fmt, b, start, o, false);
        break;
      }
      start = b;
      if (b === floor) break;
    }
    // Right end: one past the last second of the run.
    let lastSec = s;
    for (let k = 0; ; k += 1) {
      if (k === PROBE_STEPS) break;
      const b = Math.min(lastSec + PROBE_MS, ceil - SEC);
      if (b <= lastSec) break;
      if (this.exact(fmt, b) !== o) {
        lastSec = this.bisect(fmt, lastSec, b, o, true);
        break;
      }
      lastSec = b;
      if (b === ceil - SEC) break;
    }
    return this.insert(i + 1, start, lastSec + SEC, o, t);
  }

  /**
   * Seconds `a` < `b`, one of them at offset `o` and the other not: the run's edge between them.
   * `right` false: `b` holds `o`, answer its first second; true: `a` holds `o`, answer its last.
   */
  private bisect(
    fmt: Intl.DateTimeFormat,
    a: number,
    b: number,
    o: number,
    right: boolean,
  ): number {
    let lo = a / SEC;
    let hi = b / SEC;
    while (hi - lo > 1) {
      const mid = Math.floor((lo + hi) / 2);
      const inRun = this.exact(fmt, mid * SEC) === o;
      if (inRun === right) lo = mid;
      else hi = mid;
    }
    return (right ? lo : hi) * SEC;
  }

  /** Stores [start, end) at offset `o` as run `at`, merged with equal touching neighbours. */
  private insert(at: number, start: number, end: number, o: number, t: number): number {
    const { starts, ends, offs } = this;
    const left = at > 0 && ends[at - 1] === start && offs[at - 1] === o;
    const right = at < this.n && starts[at] === end && offs[at] === o;
    if (left && right) {
      ends[at - 1] = ends[at] as number;
      this.remove(at);
      this.last = at - 1;
      return o;
    }
    if (left) {
      ends[at - 1] = end;
      this.last = at - 1;
      return o;
    }
    if (right) {
      starts[at] = start;
      this.last = at;
      return o;
    }
    if (this.n === this.cap) {
      // Evict the run farthest from `t`: the table's first or last.
      const head = t - (ends[0] as number);
      const tail = (starts[this.n - 1] as number) - t;
      if (head >= tail) {
        this.remove(0);
        at -= 1;
      } else this.n -= 1;
    }
    starts.copyWithin(at + 1, at, this.n);
    ends.copyWithin(at + 1, at, this.n);
    offs.copyWithin(at + 1, at, this.n);
    starts[at] = start;
    ends[at] = end;
    offs[at] = o;
    this.n += 1;
    this.last = at;
    return o;
  }

  private remove(at: number): void {
    this.starts.copyWithin(at, at + 1, this.n);
    this.ends.copyWithin(at, at + 1, this.n);
    this.offs.copyWithin(at, at + 1, this.n);
    this.n -= 1;
  }

  /** The offset at the second holding UTC ms `t`, read from the formatter (it allocates). */
  private exact(fmt: Intl.DateTimeFormat, t: number): number {
    const s = Math.floor(t / 1000) * 1000;
    this.reads += 1;
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
