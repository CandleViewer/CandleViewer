// VolumeRing (E12-S08 pre-stage, E12-D06 §12, #534 plan BQ-2, BQ-6, BQ-7): the volume view
// transform of a `CandleRing`. Installed as the ring's derived write (`ring.setMode(store, false,
// new VolumeRing(q))`, the seam `HaRing` uses), it fills the SAME instance words from the price
// store's columns, so volume borrows the price series' bars (no second `BarStore`) and renders
// through the existing `candle` program's body part: instance = [0, v, 0, v] with v = volume in
// int32 ticks of the quantum `q` (the instrument's qty_step, passed in by the caller). The
// direction in `meta` is the REAL open / close direction (D06 §12: not Heikin-Ashi, not the
// previous close; O = C is doji, neutral). A bar whose volume is unavailable (the caller's flag
// bit, or a non-finite / negative value) is written at `UNAVAILABLE_TICK`, far below any pane,
// with `VOLUME_UNAVAILABLE` set in `meta`: it draws nothing (AC-5) and the readout and extent
// read the bit. Zero volume stays zero (a zero-height column). Bars are independent, so a write
// is exactly the mutated range plus what the ring's derived path adds. No DOM, no GL.
import type { BarStore } from "../../model/BarStore.js";
import { CANDLE_STRIDE, candleDir, outside, type RingTransform } from "../candle/ring.js";

/** The default quantum when the caller passes none (BTCUSDT's qty_step, plan BQ-6). */
export const DEFAULT_QUANTUM = 1e-3;
/** The largest column, in ticks; larger volumes clamp (counted in `VolumeRing.clamped`). */
export const MAX_TICKS = 2 ** 30 - 1;
/** Where an unavailable bar is written: below the pane, so its column is clipped away. */
export const UNAVAILABLE_TICK = -(2 ** 30);
/** `meta` bit 6 (left to other marks by the candle ring's bit table): the bar has no volume. */
export const VOLUME_UNAVAILABLE = 0x40;
/** the `dir` bits (4..5) of `meta`: a flag mask may not overlap them. */
const RESERVED_MASK = 0x30;

/** Volume in ticks: round half up, clamped to [0, MAX_TICKS]. `v` must be finite and >= 0. */
export const quantise = (v: number, quantum: number): number =>
  Math.min(MAX_TICKS, Math.floor(v / quantum + 0.5));

export class VolumeRing implements RingTransform {
  /** Volumes clamped to `MAX_TICKS` since construction (a quantum too fine for the data). */
  clamped = 0;
  /** Bars written since construction. */
  computed = 0;

  /**
   * `quantum`: base-asset units per tick, > 0. `unavailableMask`: the `BarStore` flag bit(s)
   * marking a bar's volume unavailable (BQ-7), 0 when the store has none; it must not overlap the
   * `dir` bits the ring owns.
   */
  constructor(
    public quantum: number = DEFAULT_QUANTUM,
    readonly unavailableMask: number = 0,
  ) {
    if (!(quantum > 0) || !Number.isFinite(quantum)) {
      throw new RangeError("chart-engine: volume quantum must be a positive finite number");
    }
    if ((unavailableMask & (RESERVED_MASK | ~0xff)) !== 0 || unavailableMask < 0) {
      throw new RangeError("chart-engine: unavailable mask overlaps the ring's meta bits");
    }
  }

  /** Changes the quantum; the caller then re-syncs the ring over [0, length) (a full rewrite). */
  setQuantum(quantum: number): void {
    if (!(quantum > 0) || !Number.isFinite(quantum)) {
      throw new RangeError("chart-engine: volume quantum must be a positive finite number");
    }
    this.quantum = quantum;
  }

  write(
    store: BarStore,
    ints: Int32Array,
    head: number,
    mask: number,
    from: number,
    to: number,
  ): void {
    const n = Math.max(0, to - from);
    this.computed += n;
    this.clamped += volumeFill(this, store, ints, head, mask, from, from + n);
  }
}

/** The loop over plain locals; returns the number of clamped columns. */
function volumeFill(
  t: VolumeRing,
  store: BarStore,
  ints: Int32Array,
  head: number,
  mask: number,
  from: number,
  to: number,
): number {
  const { open, high, low, close, volume, flags } = store.columns;
  const q = t.quantum;
  const na = t.unavailableMask;
  let clamped = 0;
  for (let i = from; i < to; i += 1) {
    const p = (head + i) & mask;
    const w = p * CANDLE_STRIDE;
    if (p >= open.length || w + CANDLE_STRIDE > ints.length) outside(p, mask + 1);
    const f = flags[p] as number;
    const v = volume[p] as number;
    const meta =
      (f & 0x0f) |
      (candleDir(open[p] as number, high[p] as number, low[p] as number, close[p] as number) << 4);
    if ((f & na) !== 0 || !(v >= 0) || v === Number.POSITIVE_INFINITY) {
      ints[w] = UNAVAILABLE_TICK;
      ints[w + 1] = UNAVAILABLE_TICK;
      ints[w + 2] = UNAVAILABLE_TICK;
      ints[w + 3] = UNAVAILABLE_TICK;
      ints[w + 4] = meta | VOLUME_UNAVAILABLE;
      continue;
    }
    const ticks = quantise(v, q);
    if (ticks === MAX_TICKS && v / q >= MAX_TICKS) clamped += 1;
    ints[w] = 0;
    ints[w + 1] = ticks;
    ints[w + 2] = 0;
    ints[w + 3] = ticks;
    ints[w + 4] = meta;
  }
  return clamped;
}
