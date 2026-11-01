// BarStore (26 §3.3, E11-T03): one series' bars as columns in a power-of-two ring. Logical index i
// lives at (head + i) & mask; growth doubles and re-linearises (one copy), eviction at maxBars
// moves head (no memmove); the ceiling capacity keeps ≥ maxBars / 4 spare slots (BQ-32). Every
// mutation is validated in full before its first write (a rejected one leaves the store
// byte-identical) and returns the range it touched, for sub-range uploads. E12-S06 adds the
// optional `flags` column (BQ-3), refuses bars no candle can draw (threat model F-02) and lets a
// live append merge into the last bar when it carries that bar's time (equal time → patch).
import { ModelCounters, type MutationRange, RangeSlot, pow2 } from "./counters.js";

export const DEFAULT_MAX_BARS = 200_000; // §8 ChartOptions.maxBars default
/** time 8 + open/high/low/close 4×4 + volume 4 + delta 4 + flags 1 bytes per slot (26 §7). */
export const BAR_BYTES = 33;

/** The `flags` bits (BQ-3); bits 4..7 are reserved and refused (the ring packs `dir` there). */
export const BAR_FLAG = { gapBefore: 1, forming: 2, partial: 4, amended: 8 } as const;
const FLAG_MASK = 0x0f;

/** A batch of bars: §8 `CandleData` plus an optional `delta` column (zeros when absent). */
export interface BarBatch {
  readonly time: Float64Array; // µs epoch, strictly increasing (BQ-34)
  readonly open: Int32Array; // ticks from priceOrigin
  readonly high: Int32Array;
  readonly low: Int32Array;
  readonly close: Int32Array;
  readonly volume: Float32Array;
  readonly delta?: Float32Array | undefined;
  /** E12-S06 (BQ-3): `BAR_FLAG` bits per bar; zeros when absent. */
  readonly flags?: Uint8Array | undefined;
  readonly priceOrigin: number;
  readonly tickSize: number;
}

export interface BarStoreOptions {
  readonly maxBars?: number;
  readonly initialCapacity?: number;
  readonly counters?: ModelCounters;
}

interface Columns {
  time: Float64Array;
  open: Int32Array;
  high: Int32Array;
  low: Int32Array;
  close: Int32Array;
  volume: Float32Array;
  delta: Float32Array;
  flags: Uint8Array;
}
const KEYS = ["time", "open", "high", "low", "close", "volume", "delta", "flags"] as const;
const allocate = (cap: number): Columns => ({
  time: new Float64Array(cap),
  open: new Int32Array(cap),
  high: new Int32Array(cap),
  low: new Int32Array(cap),
  close: new Int32Array(cap),
  volume: new Float32Array(cap),
  delta: new Float32Array(cap),
  flags: new Uint8Array(cap),
});

/** The §8 `BarView`: views into the store's ring over bars [0, length), valid until the next
 * mutation. The arrays are writable store memory (§8's `Readonly` is shallow): read only. */
export class BarView {
  time: Float64Array = new Float64Array(0);
  open: Int32Array = new Int32Array(0);
  high: Int32Array = new Int32Array(0);
  low: Int32Array = new Int32Array(0);
  close: Int32Array = new Int32Array(0);
  volume: Float32Array = new Float32Array(0);
  delta: Float32Array = new Float32Array(0);
  flags: Uint8Array = new Uint8Array(0);
  priceOrigin = 0;
  tickSize = 0;
  length = 0;
}

export class BarStore {
  readonly counters: ModelCounters;
  readonly maxBars: number;
  private readonly initial: number;
  private readonly ceilCap: number;
  private c: Columns;
  private cap: number;
  private head = 0;
  private n = 0;
  private origin = 0;
  private tick = 0;
  private readonly range = new RangeSlot();
  private readonly bars = new BarView();
  private viewOf: Columns | null = null;
  private viewHead = -1;

  constructor(opts: BarStoreOptions = {}) {
    const max = opts.maxBars ?? DEFAULT_MAX_BARS;
    if (!Number.isInteger(max) || max < 1 || max > 2 ** 26) {
      throw new RangeError("chart-engine: maxBars must be an integer in [1, 2^26]");
    }
    this.maxBars = max;
    this.counters = opts.counters ?? new ModelCounters();
    const init = opts.initialCapacity ?? 1024;
    if (!Number.isInteger(init) || init < 1) {
      throw new RangeError("chart-engine: initialCapacity must be a positive integer");
    }
    this.ceilCap = pow2(max + Math.max(1, max >> 2));
    this.initial = pow2(Math.min(init, max));
    this.cap = this.initial;
    this.c = allocate(this.cap);
  }

  get length(): number {
    return this.n;
  }
  get capacity(): number {
    return this.cap;
  }
  get priceOrigin(): number {
    return this.origin;
  }
  get tickSize(): number {
    return this.tick;
  }
  /** `engine.model.bytes{store="bars"}`. */
  get bytes(): number {
    return this.cap * BAR_BYTES;
  }
  /** The ring's backing columns (tests and the batch builder's upload source); read only. */
  get columns(): Readonly<Columns> {
    return this.c;
  }
  get ringHead(): number {
    return this.head;
  }

  /**
   * Appends bars at the end; at maxBars the oldest are evicted and `indexShift` says how many.
   * With `merge` (E12-S06, the live feed), a first bar carrying the last bar's time overwrites it:
   * the range then starts at that bar, and a batch of that one bar alone is a `patch`.
   */
  append(b: BarBatch, merge = false): MutationRange {
    const k = this.check(b);
    const last = this.n > 0 ? this.timeAt(this.n - 1) : -Infinity;
    const first = k > 0 ? (b.time[0] as number) : Infinity;
    const merged = merge && first === last ? 1 : 0;
    if (first <= last && merged === 0) {
      this.counters.reject("order", "append is not newer than the last bar held");
    }
    this.adopt(b);
    const add = k - merged;
    const fill = this.n + add; // capFor only when it can change the capacity: off the hot path
    if (this.cap < this.ceilCap && (fill > this.cap || fill >= this.maxBars)) {
      this.grow(this.capFor(Math.min(fill, this.maxBars)), 0, add);
    }
    const evict = Math.max(0, this.n + add - this.maxBars); // ≤ n - 1: the merged bar survives
    if (evict > 0) {
      this.head = (this.head + evict) & (this.cap - 1);
      this.n -= evict;
      this.counters.evictions += evict;
    }
    const from = this.n - merged;
    for (let j = 0; j < k; j += 1) this.put(from + j, b, j);
    this.n += add;
    return this.range.set(add === 0 && k > 0 ? "patch" : "append", from, this.n, evict);
  }

  /** Overwrites bars [index, index + count) in place, keeping time order with its neighbours. */
  patch(index: number, b: BarBatch): MutationRange {
    const k = this.check(b);
    if (!Number.isInteger(index) || index < 0 || index + k > this.n) {
      this.counters.reject("range", `patch [${index}, +${k}) outside the ${this.n} bars held`);
    }
    const before = index > 0 && k > 0 && (b.time[0] as number) <= this.timeAt(index - 1);
    const after =
      index + k < this.n && k > 0 && (b.time[k - 1] as number) >= this.timeAt(index + k);
    if (before || after) this.counters.reject("order", "patch breaks the time order");
    for (let j = 0; j < k; j += 1) this.put(index + j, b, j);
    return this.range.set("patch", index, index + k, 0);
  }

  /** Splices older bars at the front: in the ring's free space, else one reallocation with room. */
  prepend(b: BarBatch): MutationRange {
    const k = this.check(b);
    if (k > 0 && this.n > 0 && (b.time[k - 1] as number) >= this.timeAt(0)) {
      this.counters.reject("order", "prepend is not older than the first bar held");
    }
    if (this.n + k > this.maxBars) this.counters.reject("ceiling", "prepend would pass maxBars");
    this.adopt(b);
    if (this.n + k > this.cap) this.grow(this.capFor(this.n + k), k, 0);
    this.head = (this.head - k) & (this.cap - 1);
    this.n += k;
    for (let j = 0; j < k; j += 1) this.put(j, b, j);
    return this.range.set("prepend", 0, k, k);
  }

  /**
   * Replaces the series (a snapshot, §9). The new columns are built in full before the swap and
   * the old ones are never written, so whatever holds the previous view still draws it: no blank
   * frame, and a rejected snapshot changes nothing.
   */
  replace(b: BarBatch): MutationRange {
    const k = this.check(b, false);
    const cap = this.capFor(Math.max(k, this.initial));
    const next = allocate(cap);
    const lead = (cap - k) >> 1; // centred, so the first history page prepends without wrapping
    for (const key of KEYS) next[key].set(b[key] ?? [], lead); // absent delta / flags: zeros
    this.c = next;
    this.cap = cap;
    this.head = lead;
    this.n = k;
    this.origin = b.priceOrigin;
    this.tick = b.tickSize;
    this.counters.reallocations += 1;
    return this.range.set("replace", 0, k, 0);
  }

  /** The time of bar i, or NaN outside [0, length). O(1). */
  indexToTime(i: number): number {
    return Number.isInteger(i) && i >= 0 && i < this.n ? this.timeAt(i) : Number.NaN;
  }

  /** The first bar at time t, else the last bar before t; -1 before the first bar. O(log n). */
  timeToIndex(t: number): number {
    if (this.n === 0 || !(t >= this.timeAt(0))) return -1;
    let lo = 0;
    let hi = this.n;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (this.timeAt(mid) < t) lo = mid + 1;
      else hi = mid;
    }
    return lo < this.n && this.timeAt(lo) === t ? lo : lo - 1;
  }

  /**
   * The §8 `BarView` over every bar held. One object for the store's life; its views are rebuilt
   * only when the columns, head or length changed (7 subarrays: so a view after each append
   * allocates). A wrapped ring is re-linearised first (one copy, counted), so views are contiguous.
   */
  view(): BarView {
    if (this.head + this.n > this.cap) this.grow(this.cap, 0, 0);
    const v = this.bars;
    if (this.viewOf !== this.c || this.viewHead !== this.head || v.length !== this.n) {
      const c = this.c;
      const h = this.head;
      const e = h + this.n;
      v.time = c.time.subarray(h, e);
      v.open = c.open.subarray(h, e);
      v.high = c.high.subarray(h, e);
      v.low = c.low.subarray(h, e);
      v.close = c.close.subarray(h, e);
      v.volume = c.volume.subarray(h, e);
      v.delta = c.delta.subarray(h, e);
      v.flags = c.flags.subarray(h, e);
      this.viewOf = c;
      this.viewHead = h;
      v.length = this.n;
    }
    v.priceOrigin = this.origin;
    v.tickSize = this.tick;
    return v;
  }

  /** Slots for `bars`: a power of two, with ≥ maxBars / 4 spare at the ceiling (BQ-32). */
  private capFor(bars: number): number {
    return bars >= this.maxBars ? this.ceilCap : pow2(bars);
  }

  private timeAt(i: number): number {
    return this.c.time[(this.head + i) & (this.cap - 1)] as number;
  }

  /** Validates a whole batch before any write; returns its count. Allocates nothing. */
  private check(b: BarBatch, sameSeries = true): number {
    const { time, open, high, low, close, volume, delta, flags } = b;
    const cs = this.counters;
    const typed =
      time instanceof Float64Array &&
      open instanceof Int32Array &&
      high instanceof Int32Array &&
      low instanceof Int32Array &&
      close instanceof Int32Array &&
      volume instanceof Float32Array &&
      (delta === undefined || delta instanceof Float32Array) &&
      (flags === undefined || flags instanceof Uint8Array);
    if (!typed) cs.reject("type", "bar columns must be the declared typed arrays");
    const k = time.length;
    if (k > this.maxBars) cs.reject("ceiling", `${k} bars declared, maxBars is ${this.maxBars}`);
    const ohlc = open.length === k && high.length === k && low.length === k && close.length === k;
    const extra = (delta !== undefined && delta.length !== k) || (flags?.length ?? k) !== k;
    if (!ohlc || volume.length !== k || extra) {
      cs.reject("length", "bar columns differ in length");
    }
    if (!Number.isFinite(b.priceOrigin) || !(b.tickSize > 0 && b.tickSize < Infinity)) {
      cs.reject("non_finite", "priceOrigin / tickSize must be finite, tickSize > 0");
    }
    if (sameSeries && this.n > 0 && (b.priceOrigin !== this.origin || b.tickSize !== this.tick)) {
      cs.reject("origin", "priceOrigin / tickSize differ from the series held");
    }
    let prev = -Infinity;
    for (let j = 0; j < k; j += 1) {
      // Typed columns: ticks are int32 by construction; f32 volume / delta can still be ±Inf / NaN.
      const t = time[j] as number;
      const v = volume[j] as number;
      const d = delta === undefined ? 0 : (delta[j] as number);
      if (!Number.isFinite(t) || !Number.isFinite(v) || !Number.isFinite(d)) {
        cs.reject("non_finite", `bar ${j}: non-finite time, volume or delta`);
      }
      if (t <= prev) cs.reject("order", `bar ${j}: time does not increase`);
      prev = t;
      // F-02 (CE-T04): low ≤ open, close ≤ high (so low ≤ high), volume ≥ 0, no reserved flag
      // bit. One branch on the hot path; the reason is worked out only for a refusal.
      const lo = low[j] as number;
      const hi = high[j] as number;
      const o = open[j] as number;
      const c = close[j] as number;
      const f = flags === undefined ? 0 : (flags[j] as number);
      if (o < lo || o > hi || c < lo || c > hi || v < 0 || f > FLAG_MASK) refuse(cs, j, v, f);
    }
    return k;
  }

  private adopt(b: BarBatch): void {
    if (this.n > 0) return;
    this.origin = b.priceOrigin;
    this.tick = b.tickSize;
  }

  /** Writes batch row j at logical index i (both in range: checked by the caller). */
  private put(i: number, b: BarBatch, j: number): void {
    const p = (this.head + i) & (this.cap - 1);
    const c = this.c;
    c.time[p] = b.time[j] as number;
    c.open[p] = b.open[j] as number;
    c.high[p] = b.high[j] as number;
    c.low[p] = b.low[j] as number;
    c.close[p] = b.close[j] as number;
    c.volume[p] = b.volume[j] as number;
    c.delta[p] = b.delta === undefined ? 0 : (b.delta[j] as number);
    c.flags[p] = b.flags === undefined ? 0 : (b.flags[j] as number);
  }

  /** Re-linearises the n bars held into `cap` slots, centred in the room left by `pre` bars about
   * to be prepended and `post` appended, so neither wraps (BQ-32); head is the first bar held. */
  private grow(cap: number, pre: number, post: number): void {
    const [old, h, n] = [this.c, this.head, this.n];
    const first = Math.min(n, this.cap - h);
    const lead = pre + (Math.max(0, cap - n - pre - post) >> 1);
    const next = allocate(cap);
    for (const key of KEYS) {
      next[key].set(old[key].subarray(h, h + first), lead);
      next[key].set(old[key].subarray(0, n - first), lead + first);
    }
    this.c = next;
    this.cap = cap;
    this.head = lead;
    this.counters.reallocations += 1;
  }
}

/** F-02's refusal, off the hot path: the first rule bar j breaks. */
function refuse(cs: ModelCounters, j: number, volume: number, flags: number): never {
  if (volume < 0) cs.reject("negative", `bar ${j}: negative volume`);
  if (flags > FLAG_MASK) cs.reject("flags", `bar ${j}: reserved flag bits set`);
  return cs.reject("relation", `bar ${j}: needs low <= open, close <= high`);
}
