// HaRing (E12-S07, E12-D06 §3.3; BQ-2, BQ-3, BQ-4): the Heikin-Ashi view transform. While HA is
// active the series' `CandleRing` writes the HA candles instead of the real ones (the ring the
// hosts' VAOs already read, so a switch remounts nothing); this object holds the recurrence's
// float64 state per physical slot, on the store's own slot mapping, and exists only while HA is
// active. HA close = (O + H + L + C) / 4; HA open = (previous HA open + previous HA close) / 2,
// seeded (O + C) / 2 at the store's first bar (BQ-2); HA high / low = max / min of the real high
// / low and the HA open and close. Values stay float64 and are rounded half-up to ticks only when
// written (BQ-4). The ring hands it [first mutated bar, length): an append or a forming update of
// the last bar transforms one bar, a patch transforms from it to the end, and a prepend or a
// reallocation (from 0) reseeds from the first bar held. An eviction recomputes nothing, so the
// bars kept keep their values. Prices elsewhere stay real (R-4): picks return the store's index
// and the legend reads the store. No DOM, no GL.
import type { BarStore } from "../../model/BarStore.js";
import { CANDLE_STRIDE, candleDir, marks, outside, type RingTransform } from "./ring.js";

/** BQ-4: round half up, on the tick grid. */
export const roundHalfUp = (x: number): number => Math.floor(x + 0.5);

export class HaRing implements RingTransform {
  /** HA open and close per physical slot (float64: the recurrence never compounds rounding). */
  open = new Float64Array(0);
  close = new Float64Array(0);
  /** Bars transformed since construction (the incremental assertion reads it). */
  computed = 0;

  /** Bytes held, for the memory row of the bench. */
  get bytes(): number {
    return this.open.byteLength + this.close.byteLength;
  }

  write(
    store: BarStore,
    ints: Int32Array,
    head: number,
    mask: number,
    from: number,
    to: number,
  ): void {
    const cap = mask + 1;
    if (this.open.length !== cap) {
      // A new capacity is a ring rewrite, so `from` is 0 here: nothing old is read.
      this.open = new Float64Array(cap);
      this.close = new Float64Array(cap);
    }
    const n = Math.max(0, to - from);
    this.computed += n;
    const c = store.columns;
    haFill(ints, this.open, this.close, head, mask, from, from + n, c);
  }
}

/** The transform's loop over plain locals (the ring's `fill` pattern: no deopt after warm-up). */
function haFill(
  ints: Int32Array,
  haOpen: Float64Array,
  haClose: Float64Array,
  head: number,
  mask: number,
  from: number,
  to: number,
  c: BarStore["columns"],
): void {
  const { open, high, low, close, flags } = c;
  const before = (head + from - 1) & mask;
  let po = from > 0 ? (haOpen[before] ?? 0) : 0;
  let pc = from > 0 ? (haClose[before] ?? 0) : 0;
  let prev = from > 0 ? (ints[before * CANDLE_STRIDE + 3] ?? 0) : 0;
  for (let i = from; i < to; i += 1) {
    const p = (head + i) & mask;
    const w = p * CANDLE_STRIDE;
    if (p >= open.length || p >= haOpen.length || w + CANDLE_STRIDE > ints.length) {
      outside(p, mask + 1);
    }
    const ro = open[p] as number;
    const rh = high[p] as number;
    const rl = low[p] as number;
    const rc = close[p] as number;
    const fc = (ro + rh + rl + rc) / 4;
    const fo = i === 0 ? (ro + rc) / 2 : (po + pc) / 2;
    haOpen[p] = fo;
    haClose[p] = fc;
    po = fo;
    pc = fc;
    const o = roundHalfUp(fo);
    const cl = roundHalfUp(fc);
    const h = Math.max(rh, o, cl);
    const l = Math.min(rl, o, cl);
    ints[w] = o;
    ints[w + 1] = h;
    ints[w + 2] = l;
    ints[w + 3] = cl;
    ints[w + 4] =
      ((flags[p] as number) & 0x0f) | (candleDir(o, h, l, cl) << 4) | marks(o, cl, prev, i);
    prev = cl;
  }
}
