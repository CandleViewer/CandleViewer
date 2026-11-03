// CandleRing (E12-S06, plan §2 "Data layout"): the GPU-side mirror of one series' `BarStore`,
// interleaved int32 instances `[open, high, low, close, meta]` slot for slot with the store's
// ring (same head, same capacity), so a logical range maps to the same physical slots on both
// sides and `GlBuffers` uploads it in place. `meta` = flags | dir << 4, the direction classified
// once at write. Each sync writes only the mutated range [from, to) and records it for every node
// drawing the ring (`BatchBuilder.patch`); a store reallocation re-linearised its slots, so the
// ring takes a new array (a new identity: the next upload is a full one, BQ-46). No DOM, no GL.
// E12-S07: two derived modes, switched in place (`setMode`, one rewrite of the same array): the
// hollow bits (`CANDLE_META`), whose colour bit reads the previous close, so a write extends by
// the next bar; and Heikin-Ashi (`HaRing`), whose recurrence runs from the first mutated bar on.
// E12-S10: `meta` carries the forming (bit 1) and amended (bit 3) flags to the shader, and every
// sync (and `setMode`) hands its written range to the follower after the write, so the marks
// read the drawn values (Heikin-Ashi's, when on).
// E12-S07 PR B: one guard slot past the ring mirrors slot 0, so the `ribbon` program's +1
// instance read (the next bar's close) stays inside its buffer at the last physical slot; the
// candle program's `data` view stops before it, so its buffer and uploads are unchanged.
import type { VertexSource } from "../../scene/gpu-types.js";
import type { BarStore } from "../../model/BarStore.js";
import { type MutationRange, RangeSlot } from "../../model/counters.js";

/** int32 words per instance: open, high, low, close, meta. */
export const CANDLE_STRIDE = 5;
/** `meta >> 4`: how the bar is drawn (E12-D06 §3), classified once at write. */
export const CANDLE_DIR = { up: 0, down: 1, doji: 2, zeroRange: 3 } as const;
/**
 * The `meta` word's bits, allocated explicitly (E12-S07): 0..3 the store's flags (`BAR_FLAG`),
 * 4..5 `dir`; 8 `hollow` (close ≥ open: the hollow candle's outline-only body) and 9 `colourUp`
 * (close ≥ the previous bar's close; the first bar held: close ≥ open), E12-D06 §4.2. Written
 * only while the ring is hollow or Heikin-Ashi; bits 6, 7 and 10..31 are left to other marks.
 */
export const CANDLE_META = { flags: 0x0f, dirShift: 4, hollow: 0x100, colourUp: 0x200 } as const;
/** `meta >> 4`, the mark the shader and the twin read: dir, then the hollow and colour-up bits. */
export const MARK = { dir: 3, hollow: 0x10, colourUp: 0x20 } as const;

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

/**
 * A derived write (E12-S07, `HaRing`): fills logical bars [from, to) of the instance words from
 * the store's columns. The ring hands it [first mutated bar, length).
 */
export interface RingTransform {
  write(
    store: BarStore,
    ints: Int32Array,
    head: number,
    mask: number,
    from: number,
    to: number,
  ): void;
}

/** A source that follows the ring's syncs (seams, marks): `rewrite` when the ring re-linearised. */
export interface RingFollower {
  sync(store: BarStore, r: MutationRange, rewrite: boolean): void;
}

export class CandleRing implements VertexSource {
  readonly stride = CANDLE_STRIDE;
  /** The instance words as floats (the `VertexSource` the GPU uploads) and as int32 (written). */
  data = new Float32Array(0);
  /** The int32 words, the guard slot included: `(capacity + 1) * CANDLE_STRIDE` once synced. */
  ints = new Int32Array(0);
  /** `data` plus the guard slot (the ribbon's source, `RibbonSource`): the same buffer. */
  guarded = new Float32Array(0);
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
  /**
   * What follows every sync: a series' gap seams (BQ-8) and forming / amended marks (E12-S10),
   * one object behind one call site (`CandleSeries`); null follows nothing.
   */
  follower: RingFollower | null = null;
  /** E12-S07 (`setMode` only): the hollow bits are written, a write extended by the next bar. */
  hollow = false;
  /** E12-S07 (BQ-3; `setMode` only): the Heikin-Ashi transform (`HaRing`) while on, else null. */
  ha: RingTransform | null = null;
  /** `hollow || ha !== null`: the syncs take `derive`, not the plain `write`. */
  private derived = false;
  private of: object | null = null;
  private cap = 0;
  /** A rewrite's range, [0, length): its upload is due now, whatever range `r` carried. */
  private readonly all = new RangeSlot();
  /** A derived mode's written range, when it differs from the mutation's. */
  private readonly span = new RangeSlot();

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
    const rewrite = cols !== this.of || store.capacity !== this.cap;
    if (rewrite) {
      this.cap = store.capacity;
      this.ints = new Int32Array((this.cap + 1) * CANDLE_STRIDE);
      this.guarded = new Float32Array(this.ints.buffer);
      this.data = this.guarded.subarray(0, this.cap * CANDLE_STRIDE);
      this.of = cols;
      this.rewrites += 1;
      if (this.derived) this.derive(store, 0, this.length);
      else this.write(store, 0, this.length);
      range = this.all.set("replace", 0, this.length, 0);
    } else if (this.derived) {
      // E12-S07: off the plain path, so a candle ring's sync is the S06 code exactly.
      this.derive(store, Math.max(0, r.from), Math.min(r.to, this.length));
      range = this.span.set(r.op, this.lastFrom, this.lastTo, r.indexShift);
    } else this.write(store, Math.max(0, r.from), Math.min(r.to, this.length));
    // After the write: the marks read the drawn words, over what was written (a derived write
    // runs past the mutation: HA to the end, hollow one bar on).
    this.follower?.sync(store, range, rewrite);
    if (this.sink === null || range.to <= range.from) return;
    for (let i = 0; i < this.nodes.length; i += 1) this.sink.patch(this.nodes[i] as string, range);
  }

  /**
   * E12-S07: switches the hollow bits and the Heikin-Ashi transform, then rewrites every bar into
   * the same array (no new identity, so the VAOs stay) and patches [0, length): the switch costs
   * one O(n) write and no store mutation. `ha` null drops the transform and its state (BQ-3).
   * No change, no write; a null `store` (a ring not yet synced) only sets the mode.
   */
  setMode(store: BarStore | null, hollow: boolean, ha: RingTransform | null): void {
    if (hollow === this.hollow && ha === this.ha) return;
    this.hollow = hollow;
    this.ha = ha;
    this.derived = hollow || ha !== null;
    if (store === null) return;
    const all = this.all.set("replace", 0, store.length, 0);
    if (store.columns !== this.of || store.capacity !== this.cap) {
      this.sync(store, all);
      return;
    }
    if (this.derived) this.derive(store, 0, this.length);
    else this.write(store, 0, this.length);
    this.follower?.sync(store, all, false); // E12-S10: the marks follow the drawn words
    if (this.sink === null || this.length === 0) return;
    for (let i = 0; i < this.nodes.length; i += 1) this.sink.patch(this.nodes[i] as string, all);
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
    this.guard();
  }

  /**
   * E12-S07 PR B: the guard slot (physical `capacity`) mirrors slot 0 after a write that covers
   * it (`lastFrom`, `lastTo`): the ribbon's next-bar read of the last slot. Five scalar copies,
   * and only then: the live tick appends far from slot 0 and pays one compare.
   */
  private guard(): void {
    const n = this.lastTo - this.lastFrom;
    const p = (this.head + this.lastFrom) & (this.cap - 1);
    if (n <= 0 || (p !== 0 && p + n <= this.cap)) return;
    const v = this.ints;
    const at = this.cap * CANDLE_STRIDE;
    v[at] = v[0] as number;
    v[at + 1] = v[1] as number;
    v[at + 2] = v[2] as number;
    v[at + 3] = v[3] as number;
    v[at + 4] = v[4] as number;
  }

  /**
   * Makes `ids` the nodes this ring patches (E12-S07 PR B: a switch between the candle and the
   * line family, whose hosts read separate GPU buffers) and patches each with [0, length): a
   * family shown again missed the syncs while hidden. Switches only, never per frame.
   */
  follow(ids: readonly string[]): void {
    this.nodes.length = 0;
    for (let i = 0; i < ids.length; i += 1) this.nodes.push(ids[i] as string);
    if (this.sink === null || this.length === 0) return;
    const all = this.all.set("replace", 0, this.length, 0);
    for (let i = 0; i < ids.length; i += 1) this.sink.patch(ids[i] as string, all);
  }

  /**
   * `write` for the derived modes (E12-S07). HA: every later bar's open follows a written one
   * (§3.3), so the write runs to the end; hollow: the next bar's colour bit reads the last
   * written close, so a write that stops short of the end takes one more bar.
   */
  private derive(store: BarStore, from: number, to: number): void {
    const ha = this.ha;
    const end = ha !== null ? this.length : to > from && to < this.length ? to + 1 : to;
    const n = Math.max(0, end - from);
    this.lastFrom = from;
    this.lastTo = from + n;
    this.written += n;
    const c = store.columns;
    const mask = this.cap - 1;
    if (ha !== null) ha.write(store, this.ints, this.head, mask, from, from + n);
    else {
      fillHollow(
        this.ints,
        this.head,
        mask,
        from,
        from + n,
        c.open,
        c.high,
        c.low,
        c.close,
        c.flags,
      );
    }
    this.guard();
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

/** `fill` plus the hollow bits (E12-D06 §4.2): close vs open, close vs the previous close. */
function fillHollow(
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
  let prev = from > 0 ? (close[(head + from - 1) & mask] ?? 0) : 0;
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
    ints[w + 4] =
      ((flags[p] as number) & 0x0f) | (candleDir(o, h, l, c) << 4) | marks(o, c, prev, i);
    prev = c;
  }
}

/** The hollow and colour-up bits of a bar at logical `i` (the first one held has no previous). */
export const marks = (o: number, c: number, prev: number, i: number): number =>
  (c >= o ? CANDLE_META.hollow : 0) | ((i === 0 ? c >= o : c >= prev) ? CANDLE_META.colourUp : 0);

export const outside = (p: number, cap: number): never => {
  throw new RangeError(`chart-engine: candle slot ${p} outside the ring of ${cap}`);
};
