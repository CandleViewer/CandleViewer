// The gap seams (E12-S06, BQ-8, E12-D06 §8): the `gap_before` bars of one series as a tiny
// instance source for the `candle` program's seam part, one hairline at each such bar's slot edge.
// An entry is the bar's physical store slot (word 0 of a CANDLE_STRIDE record, read as `a_ohlc.x`),
// so a pan, a prepend or an eviction moves no entry: the shader maps the slot to its bar through
// the ring's (head, mask). Entries stay sorted by logical index; a mutation rescans only its own
// range (a store reallocation or a `replace`: everything). An unchanged list patches nothing.
import type { VertexSource } from "../../scene/gpu-types.js";
import type { BarStore } from "../../model/BarStore.js";
import { type MutationRange, RangeSlot } from "../../model/counters.js";
import { CANDLE_STRIDE, type RangePatchSink } from "./ring.js";

/** `flags` bit 0 (24 §19.75): a coverage hole before this bar. */
export const FLAG_GAP_BEFORE = 1;
const MIN_CAPACITY = 16;

export class SeamRing implements VertexSource {
  readonly stride = CANDLE_STRIDE;
  /** Always 0: entries are packed from the start; the slot they name carries the ring's head. */
  readonly head = 0;
  ints = new Int32Array(MIN_CAPACITY * CANDLE_STRIDE);
  data = new Float32Array(this.ints.buffer);
  /** Live entries, `[0, count)`. */
  count = 0;
  /** Nodes drawing the seams: a changed list patches their batches. */
  readonly nodes: string[] = [];
  /** Lists rebuilt (changed) so far: read by tests. */
  changes = 0;
  /** The previous list's slots, compared with the new one (reused, never per call). */
  private prev = new Int32Array(MIN_CAPACITY);
  private readonly range = new RangeSlot();

  /** `owner.sink` is read at each change: the ring's, which a degraded-2d re-init replaces. */
  constructor(private readonly owner: { readonly sink: RangePatchSink | null } = { sink: null }) {}

  /** `InstanceRing.length`: the live entries. */
  get length(): number {
    return this.count;
  }

  /** Instance slots in the buffer: the seam batch's draw covers `[0, count)` of them. */
  get capacity(): number {
    return this.ints.length / CANDLE_STRIDE;
  }

  /** The logical index of entry `e` under the store ring's (head, mask). */
  indexOf(e: number, head: number, mask: number): number {
    return ((this.ints[e * CANDLE_STRIDE] ?? 0) - head) & mask;
  }

  /**
   * Mirrors the gap flags after mutation `r` of `store`. `rewrite` (the CandleRing re-linearised
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
      if (((flags[p] as number) & FLAG_GAP_BEFORE) !== 0) found += 1;
    }
    const before = this.count;
    if (found === 0 && !all) {
      // The common live tick: nothing new; skip unless a kept entry falls in the range.
      let touched = false;
      for (let k = 0; !touched && k < before; k += 1) {
        const idx = this.indexOf(k, head, mask);
        touched = idx >= n || (idx >= from && idx < to);
      }
      if (!touched) return;
    }
    if (this.prev.length < before) this.prev = new Int32Array(this.capacity);
    for (let k = 0; k < before; k += 1) this.prev[k] = this.ints[k * CANDLE_STRIDE] ?? 0;
    this.reserve(before + found);
    // Kept entries keep their order (a head move shifts them all alike; an evicted bar's slot now
    // holds a bar of the rescanned range): those below `from`, then the range's, then the rest.
    let e = 0;
    let k = 0;
    if (!all) {
      for (; k < before; k += 1) {
        const idx = ((this.prev[k] as number) - head) & mask;
        if (idx >= n || (idx >= from && idx < to)) continue;
        if (idx >= to) break;
        e = this.put(e, this.prev[k] as number);
      }
    }
    for (let i = from; i < to; i += 1) {
      const p = (head + i) & mask;
      if (((flags[p] as number) & FLAG_GAP_BEFORE) !== 0) e = this.put(e, p);
    }
    for (; !all && k < before; k += 1) {
      const idx = ((this.prev[k] as number) - head) & mask;
      if (idx < n && (idx < from || idx >= to)) e = this.put(e, this.prev[k] as number);
    }
    this.count = e;
    let same = e === before;
    for (let j = 0; same && j < e; j += 1) same = this.ints[j * CANDLE_STRIDE] === this.prev[j];
    if (same) return;
    this.changes += 1;
    const sink = this.owner.sink;
    if (sink === null) return;
    const span = this.range.set("replace", 0, Math.max(e, before), 0);
    for (let j = 0; j < this.nodes.length; j += 1) sink.patch(this.nodes[j] as string, span);
  }

  private put(e: number, slot: number): number {
    const w = e * CANDLE_STRIDE;
    if (w + CANDLE_STRIDE > this.ints.length) outside(e, this.capacity);
    this.ints[w] = slot;
    this.ints[w + 1] = this.ints[w + 2] = this.ints[w + 3] = this.ints[w + 4] = 0;
    return e + 1;
  }

  /**
   * Whether any seam's bar lies in logical `[first, last]`: a binary search over the sorted
   * entries, once per frame (the seam draw happens only then, BQ-8).
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
    let cap = this.capacity;
    if (n <= cap) return;
    while (cap < n) cap *= 2;
    const next = new Int32Array(cap * CANDLE_STRIDE);
    next.set(this.ints.subarray(0, this.count * CANDLE_STRIDE));
    this.ints = next;
    this.data = new Float32Array(next.buffer);
  }
}

const outside = (p: number, cap: number): never => {
  throw new RangeError(`chart-engine: seam slot ${p} outside the flags column of ${cap}`);
};
