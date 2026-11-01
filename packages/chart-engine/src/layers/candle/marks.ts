// The bar-state marks (E12-S10, E12-D06 §7.1 / §7.3): the forming and amended bars of one series
// as a tiny instance source for the `candle` program's marks part (7), the SeamRing pattern. An
// entry is one mark: [store slot, high, low, open, kind | dir << 4 | heavy] of the drawn bar (the
// ring's words: under Heikin-Ashi the HA candle, E12-S07), `kind` the flag bit drawn (`forming`:
// the dashed ring; `amended`: the square), so a bar with both bits has two entries; `heavy`
// (`MARK_HEAVY`) the drawn wick's 2-hairline weight (down; hollow: colour-down, D06 §4.2).
// The slot maps to the bar through the ring's (head, mask), so a pan, a prepend or an eviction
// moves no entry; the open, high and low place the mark (the close lies inside the wick, or equals
// the open on a doji), so a live tick that moves only the close leaves a candle entry unchanged and
// uploads nothing here (under HA or hollow the drawn words may move: one entry patched). Entries
// stay sorted by logical index, then kind; a mutation rescans only the ring's written range (a
// store reallocation, a `replace` or a mode switch: everything) and patches only the entries
// that changed. Each change of a bar's (forming, amended) state is queued for `barStateChanged`.
import { BAR_FLAG, type BarStore } from "../../model/BarStore.js";
import { type MutationRange, RangeSlot } from "../../model/counters.js";
import { MARK_HEAVY } from "./geometry.js";
import { CANDLE_DIR, CANDLE_META, CANDLE_STRIDE, MARK, type RangePatchSink } from "./ring.js";

/** What a `MarkRing` reads from its `CandleRing` (structurally). */
export interface MarkOwner {
  readonly sink: RangePatchSink | null;
  readonly ints: Int32Array;
  readonly hollow: boolean;
}

/** The flag bits a mark draws: the forming ring and the corrected square. */
export const MARK_BITS = BAR_FLAG.forming | BAR_FLAG.amended;
const MIN_CAPACITY = 4;

/** A `VertexSource` structurally (no import from src/gl: the layers never reach GL, C-2.16). */
export class MarkRing {
  readonly stride = CANDLE_STRIDE;
  /** Always 0: entries are packed from the start; the slot they name carries the ring's head. */
  readonly head = 0;
  ints = new Int32Array(MIN_CAPACITY * CANDLE_STRIDE);
  data = new Float32Array(this.ints.buffer);
  /** Each entry's bar time (CPU only: the state events name bars by time). */
  times = new Float64Array(MIN_CAPACITY);
  /** Live entries, `[0, count)`. */
  count = 0;
  /** Nodes drawing the marks: a changed entry patches their batches. */
  readonly nodes: string[] = [];
  /** Syncs that changed an entry, and entries written to the GPU copy: read by tests. */
  changes = 0;
  patched = 0;
  /**
   * Bar state changes since the last `takeEvents`: `[0, events)` of `eventTimes` (the bar's time)
   * and `eventBits` (its `forming | amended` bits now). Never one per tick: a tick that keeps the
   * bits queues nothing. An evicted or replaced-away bar queues nothing (it has no state).
   */
  events = 0;
  eventTimes = new Float64Array(MIN_CAPACITY);
  eventBits = new Uint8Array(MIN_CAPACITY);
  /** The previous list (reused, never per call): its words and times. */
  private prev = new Int32Array(MIN_CAPACITY * CANDLE_STRIDE);
  private prevTimes = new Float64Array(MIN_CAPACITY);
  private readonly range = new RangeSlot();

  /**
   * `owner` is the series' `CandleRing`: `sink` is read at each change (a degraded-2d re-init
   * replaces it); `ints` and `hollow` are the drawn words and mode the entries copy (E12-S07).
   */
  constructor(private readonly owner: MarkOwner) {}

  /** `InstanceRing.length`: the live entries. */
  get length(): number {
    return this.count;
  }

  /**
   * Instance slots the batch spans (`InstanceRing.capacity`, the host's batch count): the
   * buffer's while any entry lives, else 0, so a series with no forming or amended bar keeps no
   * marks batch in the draw list (nothing per frame). Every change re-collects the host
   * (`CandleSeries.dirtyHosts`); the draw covers `[0, count)`.
   */
  get capacity(): number {
    return this.count > 0 ? this.slots : 0;
  }

  /** Entries the buffer holds. */
  get slots(): number {
    return this.ints.length / CANDLE_STRIDE;
  }

  /** The logical index of entry `e` under the store ring's (head, mask). */
  indexOf(e: number, head: number, mask: number): number {
    return ((this.ints[e * CANDLE_STRIDE] ?? 0) - head) & mask;
  }

  /** The flag bit entry `e` draws (`BAR_FLAG.forming` or `.amended`). */
  kindOf(e: number): number {
    return (this.ints[e * CANDLE_STRIDE + 4] ?? 0) & MARK_BITS;
  }

  /**
   * Mirrors the marked bars after mutation `r` of `store`. `rewrite` (the CandleRing re-linearised
   * its slots) or a `replace` rescans the whole store; otherwise entries inside `[r.from, r.to)`
   * or past the store's length are dropped and that range is rescanned.
   */
  sync(store: BarStore, r: MutationRange, rewrite: boolean): void {
    const n = store.length;
    const mask = store.capacity - 1;
    const head = store.ringHead;
    const all = rewrite || r.op === "replace";
    const from = all ? 0 : Math.max(0, r.from);
    const to = all ? n : Math.max(from, Math.min(r.to, n));
    const flags = store.columns.flags;
    let found = 0;
    for (let i = from; i < to; i += 1) {
      const p = (head + i) & mask;
      if (p >= flags.length) outside(p, flags.length);
      const f = flags[p] as number;
      found += ((f >> 1) & 1) + ((f >> 3) & 1); // one entry per bit: forming (2), amended (8)
    }
    const before = this.count;
    if (found === 0 && !all) {
      // The common case: no mark in the range; skip unless a kept entry falls in it or past n.
      let touched = false;
      for (let k = 0; !touched && k < before; k += 1) {
        const idx = this.indexOf(k, head, mask);
        touched = idx >= n || (idx >= from && idx < to);
      }
      if (!touched) return;
    }
    this.keep(before);
    this.reserve(before + found);
    // Kept entries keep their order (a head move shifts them all alike; an evicted bar's slot now
    // holds a bar of the rescanned range): those below `from`, then the range's, then the rest.
    let e = 0;
    let k = 0;
    if (!all) {
      for (; k < before; k += 1) {
        const idx = this.prevIndex(k, head, mask);
        if (idx >= n || (idx >= from && idx < to)) continue;
        if (idx >= to) break;
        e = this.copy(e, k);
      }
    }
    const c = store.columns;
    for (let i = from; i < to; i += 1) {
      const p = (head + i) & mask;
      const f = (c.flags[p] as number) & MARK_BITS;
      if (f === 0) continue;
      const t = c.time[p] as number;
      if ((f & BAR_FLAG.forming) !== 0) e = this.put(e, p, BAR_FLAG.forming, t);
      if ((f & BAR_FLAG.amended) !== 0) e = this.put(e, p, BAR_FLAG.amended, t);
    }
    for (; !all && k < before; k += 1) {
      const idx = this.prevIndex(k, head, mask);
      if (idx < n && (idx < from || idx >= to)) e = this.copy(e, k);
    }
    this.count = e;
    this.diff(e, before, store);
  }

  /** Copies the live list into `prev` (grown with the list, never per call once warm). */
  private keep(before: number): void {
    if (this.prev.length < this.ints.length) {
      this.prev = new Int32Array(this.ints.length);
      this.prevTimes = new Float64Array(this.times.length);
    }
    this.prev.set(this.ints.subarray(0, before * CANDLE_STRIDE));
    this.prevTimes.set(this.times.subarray(0, before));
  }

  private prevIndex(k: number, head: number, mask: number): number {
    return ((this.prev[k * CANDLE_STRIDE] as number) - head) & mask;
  }

  /** Kept entry `k` of the previous list to entry `e`: its words did not change. */
  private copy(e: number, k: number): number {
    const w = e * CANDLE_STRIDE;
    const v = k * CANDLE_STRIDE;
    if (w + CANDLE_STRIDE > this.ints.length) outside(e, this.slots);
    for (let j = 0; j < CANDLE_STRIDE; j += 1) this.ints[w + j] = this.prev[v + j] as number;
    this.times[e] = this.prevTimes[k] as number;
    return e + 1;
  }

  private put(e: number, slot: number, kind: number, t: number): number {
    const w = e * CANDLE_STRIDE;
    if (w + CANDLE_STRIDE > this.ints.length) outside(e, this.slots);
    // The drawn words (the ring writes before its follower runs): the store's bar, or under
    // Heikin-Ashi its HA candle, so the ring circles and the square tops what is on screen.
    const words = this.owner.ints;
    const v = slot * CANDLE_STRIDE;
    if (v + CANDLE_STRIDE > words.length) outside(slot, words.length / CANDLE_STRIDE);
    const o = words[v] as number;
    const h = words[v + 1] as number;
    const l = words[v + 2] as number;
    const meta = words[v + 4] as number;
    const dir = (meta >> CANDLE_META.dirShift) & MARK.dir;
    const heavy =
      this.owner.hollow && dir !== CANDLE_DIR.zeroRange
        ? (meta & CANDLE_META.colourUp) === 0
        : dir === CANDLE_DIR.down;
    this.ints[w] = slot;
    this.ints[w + 1] = h;
    this.ints[w + 2] = l;
    this.ints[w + 3] = o;
    this.ints[w + 4] = kind | (dir << CANDLE_META.dirShift) | (heavy ? MARK_HEAVY : 0);
    this.times[e] = t;
    return e + 1;
  }

  /**
   * Patches the first through the last changed entry below `e` (a shrink needs no upload: the
   * draw covers `[0, count)`), then queues the bars whose state changed: a merge walk over the two
   * time-sorted lists. A bar that left both lists but is still in the store lost its bits.
   */
  private diff(e: number, before: number, store: BarStore): void {
    const ints = this.ints;
    const prev = this.prev;
    let lo = -1;
    let hi = -1;
    const both = Math.min(e, before);
    for (let j = 0; j < both; j += 1) {
      const w = j * CANDLE_STRIDE;
      let same = true;
      for (let q = 0; same && q < CANDLE_STRIDE; q += 1) same = ints[w + q] === prev[w + q];
      if (same && this.times[j] === this.prevTimes[j]) continue;
      if (lo < 0) lo = j;
      hi = j + 1;
    }
    if (e > before) {
      if (lo < 0) lo = before;
      hi = e;
    }
    if (lo < 0 && e === before) return;
    this.changes += 1;
    this.queue(e, before, store);
    const sink = this.owner.sink;
    if (sink === null || lo < 0) return;
    this.patched += hi - lo;
    const span = this.range.set("patch", lo, hi, 0);
    for (let j = 0; j < this.nodes.length; j += 1) sink.patch(this.nodes[j] as string, span);
  }

  /** The merge walk: per bar time, its bits before and now; a difference queues one event. */
  private queue(e: number, before: number, store: BarStore): void {
    let a = 0;
    let b = 0;
    while (a < before || b < e) {
      const ta = a < before ? (this.prevTimes[a] as number) : Infinity;
      const tb = b < e ? (this.times[b] as number) : Infinity;
      const t = Math.min(ta, tb);
      let was = 0;
      let now = 0;
      for (; a < before && this.prevTimes[a] === t; a += 1) {
        was |= (this.prev[a * CANDLE_STRIDE + 4] as number) & MARK_BITS;
      }
      for (; b < e && this.times[b] === t; b += 1) {
        now |= (this.ints[b * CANDLE_STRIDE + 4] as number) & MARK_BITS;
      }
      if (was === now) continue;
      if (now === 0) {
        const at = store.timeToIndex(t);
        if (at < 0 || store.indexToTime(at) !== t) continue; // evicted or replaced away
      }
      this.push(t, now);
    }
  }

  private push(t: number, bits: number): void {
    if (this.events === this.eventTimes.length) {
      const times = new Float64Array(this.events * 2);
      const bits2 = new Uint8Array(this.events * 2);
      times.set(this.eventTimes);
      bits2.set(this.eventBits);
      this.eventTimes = times;
      this.eventBits = bits2;
    }
    this.eventTimes[this.events] = t;
    this.eventBits[this.events] = bits;
    this.events += 1;
  }

  /** Empties the event queue; the caller reads `[0, n)` of `eventTimes` / `eventBits` first. */
  takeEvents(): number {
    const n = this.events;
    this.events = 0;
    return n;
  }

  /**
   * Whether any mark's bar lies in logical `[first, last]`: a binary search over the sorted
   * entries, once per frame (the marks draw happens only then).
   */
  anyIn(first: number, last: number, head: number, mask: number): boolean {
    let lo = 0;
    let hi = this.count;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.indexOf(mid, head, mask) < first) lo = mid + 1;
      else hi = mid;
    }
    return lo < this.count && this.indexOf(lo, head, mask) <= last;
  }

  /** Grows the buffer to hold `n` entries (doubling): a new array, so the next upload is full. */
  private reserve(n: number): void {
    let cap = this.slots;
    if (n <= cap) return;
    while (cap < n) cap *= 2;
    const next = new Int32Array(cap * CANDLE_STRIDE);
    next.set(this.ints.subarray(0, this.count * CANDLE_STRIDE));
    const times = new Float64Array(cap);
    times.set(this.times.subarray(0, this.count));
    this.ints = next;
    this.data = new Float32Array(next.buffer);
    this.times = times;
  }
}

const outside = (p: number, cap: number): never => {
  throw new RangeError(`chart-engine: mark slot ${p} outside the flags column of ${cap}`);
};
