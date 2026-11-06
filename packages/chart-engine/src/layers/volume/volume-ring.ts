// VolumeRing (E12-S08 PR 1, E12-D06 §12; #534 BQ-2, BQ-6, BQ-7): the volume view transform of a
// `CandleRing`. Installed as the ring's derived write (`ring.setMode(store, false, ring)`, the
// seam `HaRing` uses), it fills the SAME slots from the price store's columns, so volume borrows
// the price series' bars (no second `BarStore`) and draws through the dedicated `volume` program:
// word 0 = the volume in int32 ticks of the quantisation step (a REQUIRED option, no default),
// words 1..3 stay 0, word 4 = `meta`: the store's flags (bits 0..3), the REAL open / close
// direction (4..5, D06 §12: not Heikin-Ashi, not the previous close), `VOLUME_UNAVAILABLE` (6)
// and `VOLUME_NEUTRAL` (7). An unavailable bar (the store's engine-internal null bit, or a
// non-finite / negative value) is written as 0 ticks with bit 6: the shader skips it, the readout
// and the extent read the bit; there is no sentinel position. Zero volume stays zero (nothing
// drawn). Bars are independent (`local`): a write is exactly the mutated range. No DOM, no GL.
import { BAR_FLAG_INTERNAL, type BarStore } from "../../model/BarStore.js";
import { CANDLE_STRIDE, candleDir, outside, type RingTransform } from "../candle/ring.js";

/** The largest column, in ticks; larger volumes clamp (counted in `VolumeRing.clamped`). */
export const MAX_TICKS = 2 ** 30 - 1;
/** `meta` bit 6: the bar has no volume (the store's engine-internal bit 6, same position). */
export const VOLUME_UNAVAILABLE: number = BAR_FLAG_INTERNAL.volumeNull;
/** `meta` bit 7: a decimated tier's column, drawn neutral (D06 §12 L1 / L2). Never a store bit. */
export const VOLUME_NEUTRAL = 0x80;

/** A refusal of the required quantisation step. */
export class VolumeQuantumError extends RangeError {
  constructor() {
    super("chart-engine: the volume quantisation step is required: a positive finite number");
    this.name = "VolumeQuantumError";
  }
}

const checkQuantum = (q: unknown): number => {
  if (typeof q !== "number" || !(q > 0) || !Number.isFinite(q)) throw new VolumeQuantumError();
  return q;
};

/** Volume in ticks: round half up, clamped to [0, MAX_TICKS]. `v` must be finite and >= 0. */
export const quantise = (v: number, quantum: number): number =>
  Math.min(MAX_TICKS, Math.floor(v / quantum + 0.5));

export class VolumeRing implements RingTransform {
  readonly local = true;
  /** Volumes clamped to `MAX_TICKS` since construction (a step too fine for the data). */
  clamped = 0;
  /** Bars written since construction. */
  computed = 0;
  /** True while a decimated tier draws: every column carries `VOLUME_NEUTRAL`. */
  neutral = false;
  private step: number;

  /** `quantum`: base-asset units per tick (the instrument's qty_step); required, > 0, finite. */
  constructor(quantum: number) {
    this.step = checkQuantum(quantum);
  }

  get quantum(): number {
    return this.step;
  }

  /** Changes the step; the caller then rewrites the ring over [0, length). */
  setQuantum(quantum: number): void {
    this.step = checkQuantum(quantum);
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
  const tier = t.neutral ? VOLUME_NEUTRAL : 0;
  let clamped = 0;
  for (let i = from; i < to; i += 1) {
    const p = (head + i) & mask;
    const w = p * CANDLE_STRIDE;
    if (p >= open.length || w + CANDLE_STRIDE > ints.length) outside(p, mask + 1);
    const f = flags[p] as number;
    const v = volume[p] as number;
    const meta =
      (f & 0x0f) |
      (candleDir(open[p] as number, high[p] as number, low[p] as number, close[p] as number) << 4) |
      tier;
    if ((f & VOLUME_UNAVAILABLE) !== 0 || !(v >= 0) || v === Number.POSITIVE_INFINITY) {
      ints[w] = 0;
      ints[w + 4] = meta | VOLUME_UNAVAILABLE;
      continue;
    }
    const ticks = quantise(v, q);
    if (ticks === MAX_TICKS && v / q >= MAX_TICKS) clamped += 1;
    ints[w] = ticks;
    ints[w + 4] = meta;
  }
  return clamped;
}
