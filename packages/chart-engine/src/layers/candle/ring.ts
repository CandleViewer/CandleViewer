// CandleRing (E12-S06, plan §2 "Data layout"): the GPU-side mirror of one series' `BarStore`,
// interleaved int32 instances `[open, high, low, close, meta]` slot for slot with the store's
// ring (same head, same capacity), so a logical range maps to the same physical slots on both
// sides and `GlBuffers` uploads it in place. `meta` = flags | dir << 4, the direction classified
// once at write. Each sync writes only the mutated range [from, to) and records it for every node
// drawing the ring (`BatchBuilder.patch`); a store reallocation re-linearised its slots, so the
// ring takes a new array (a new identity: the next upload is a full one, BQ-46). No DOM, no GL.
import type { VertexSource } from "../../gl/buffers.js";
import type { BarStore } from "../../model/BarStore.js";
import { type MutationRange, RangeSlot } from "../../model/counters.js";

/** int32 words per instance: open, high, low, close, meta. */
export const CANDLE_STRIDE = 5;
/** `meta >> 4`: how the bar is drawn (E12-D06 §3), classified once at write. */
export const CANDLE_DIR = { up: 0, down: 1, doji: 2, zeroRange: 3 } as const;

/** Where the ring reports its writes: `BatchBuilder.patch`, structurally. */
export interface RangePatchSink {
  patch(nodeId: string, r: MutationRange): void;
}

/** O = H = L = C: zero-range; O = C: doji; else up when close > open. */
export const candleDir = (o: number, h: number, l: number, c: number): number =>
  o === c
    ? h === l
      ? CANDLE_DIR.zeroRange
      : CANDLE_DIR.doji
    : c > o
      ? CANDLE_DIR.up
      : CANDLE_DIR.down;

export class CandleRing implements VertexSource {
  readonly stride = CANDLE_STRIDE;
  /** The instance words as floats (the `VertexSource` the GPU uploads) and as int32 (written). */
  data = new Float32Array(0);
  ints = new Int32Array(0);
  head = 0;
  /** Bars mirrored: the store's length at the last sync. */
  length = 0;
  /** Instances written since construction, and full rewrites (store reallocations). */
  written = 0;
  rewrites = 0;
  /** The last sync's written logical range [from, to); the whole ring after a rewrite. */
  lastFrom = 0;
  lastTo = 0;
  /** Nodes that draw this ring: each sync patches their batches. */
  readonly nodes: string[] = [];
  private of: object | null = null;
  private cap = 0;
  /** A rewrite's range, [0, length): its upload is due now, whatever range `r` carried. */
  private readonly all = new RangeSlot();

  constructor(public sink: RangePatchSink | null = null) {}

  /** Physical slots in the ring; the draw's instance count is the ring capacity (plan §2). */
  get capacity(): number {
    return this.cap;
  }

  /**
   * Mirrors `store` after the mutation `r` (its return value). A reallocated store (new columns)
   * is rewritten in full into a new array, and every attached node's batch is patched with
   * [0, length); otherwise only [r.from, r.to) is written and patched. An empty range patches
   * nothing (`BatchBuilder.patch` would keep its `to` as a stale upload bound).
   */
  sync(store: BarStore, r: MutationRange): void {
    const cols = store.columns;
    this.head = store.ringHead;
    this.length = store.length;
    let range = r;
    if (cols !== this.of || store.capacity !== this.cap) {
      this.cap = store.capacity;
      this.ints = new Int32Array(this.cap * CANDLE_STRIDE);
      this.data = new Float32Array(this.ints.buffer);
      this.of = cols;
      this.rewrites += 1;
      this.write(store, 0, this.length);
      range = this.all.set("replace", 0, this.length, 0);
    } else this.write(store, Math.max(0, r.from), Math.min(r.to, this.length));
    if (this.sink === null || range.to <= range.from) return;
    for (let i = 0; i < this.nodes.length; i += 1) this.sink.patch(this.nodes[i] as string, range);
  }

  /**
   * Writes logical bars [from, to) at their physical slots, each slot bounds-checked. Every
   * field is written before the loop: code after a hot loop has no type feedback when the first
   * (full) write optimises on-stack, and would deoptimise on every later call.
   */
  private write(store: BarStore, from: number, to: number): void {
    const n = Math.max(0, to - from);
    this.lastFrom = from;
    this.lastTo = from + n;
    this.written += n;
    const c = store.columns;
    fill(
      this.ints,
      this.head,
      this.cap - 1,
      from,
      from + n,
      c.open,
      c.high,
      c.low,
      c.close,
      c.flags,
    );
  }
}

/** The ring's write loop over plain locals (see `write`). */
function fill(
  ints: Int32Array,
  head: number,
  mask: number,
  from: number,
  to: number,
  open: Int32Array,
  high: Int32Array,
  low: Int32Array,
  close: Int32Array,
  flags: Uint8Array,
): void {
  for (let i = from; i < to; i += 1) {
    const p = (head + i) & mask;
    const w = p * CANDLE_STRIDE;
    if (p >= open.length || w + CANDLE_STRIDE > ints.length) outside(p, mask + 1);
    const o = open[p] as number;
    const h = high[p] as number;
    const l = low[p] as number;
    const c = close[p] as number;
    ints[w] = o;
    ints[w + 1] = h;
    ints[w + 2] = l;
    ints[w + 3] = c;
    ints[w + 4] = ((flags[p] as number) & 0x0f) | (candleDir(o, h, l, c) << 4);
  }
}

const outside = (p: number, cap: number): never => {
  throw new RangeError(`chart-engine: candle slot ${p} outside the ring of ${cap}`);
};
