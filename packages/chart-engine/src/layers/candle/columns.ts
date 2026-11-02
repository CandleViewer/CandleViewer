// The L2 column mark's data side (E12-S09 PR 1, #421 BQ-02 / BQ-05 / BQ-06): what the candle
// renderer consumes from E11-S12's (#418) decimator, not the decimator itself. `ColumnSource` is
// the structural shape S12's `ColumnStrip` must satisfy (26 §3.6: one column per device px, the
// survivors in integer ticks); `ColumnEntries` turns one into `candle` instances (parts 7 / 8)
// in a buffer preallocated to the device width, writing and patching only the entries that
// changed; the forming bar is its own entry, never folded (D06 §5.4, `14`:754). `foldVolumeMax`
// is the volume sub-pane's neutral max per column (D06 §12) for E12-S08. No DOM, no GL.
import type { VertexSource } from "../../scene/gpu-types.js";
import { BAR_FLAG, type BarStore } from "../../model/BarStore.js";
import { RangeSlot } from "../../model/counters.js";
import { CANDLE_STRIDE, candleDir, type RangePatchSink } from "./ring.js";

/** A source column's words (26 §3.6); words past these are the source's own (volume, …). */
export const COLUMN_WORD = { minLow: 0, maxHigh: 1, firstOpen: 2, lastClose: 3 } as const;
/** The largest device column an entry can carry (`meta = column << 4 | dir`, int32). */
export const MAX_COLUMN = 2 ** 27 - 1;

/**
 * E11-S12's column strip, structurally (BQ-02): `count` columns of `stride` (≥ 4) int32 words,
 * entry j the device column `firstColumn + j`. A column no bar falls in has minLow > maxHigh.
 */
export interface ColumnSource {
  readonly ints: Int32Array;
  readonly stride: number;
  readonly count: number;
  readonly firstColumn: number;
}

/** True when the store's last bar is forming: the decimator folds bars [first, `foldEnd`). */
export const formingLast = (store: BarStore): boolean =>
  store.length > 0 &&
  ((store.columns.flags[(store.ringHead + store.length - 1) & (store.capacity - 1)] ?? 0) &
    BAR_FLAG.forming) !==
    0;

/** BQ-05: the exclusive end of the bars a column may fold: the forming bar never is. */
export const foldEnd = (store: BarStore): number => store.length - (formingLast(store) ? 1 : 0);

/**
 * The L2 instances: per entry `[firstOpen, maxHigh, minLow, lastClose, column << 4 | dir]`, the
 * `candle` VAO's layout (a_ohlc, a_meta), drawn as `u_batch` = (part, 0, -1, count). Grows only
 * in `reserve` (E11-S10's 128 px steps; a new identity, so the next upload is a full one); each
 * `write` changes the words of the entries that differ and patches their range.
 */
export class ColumnEntries implements VertexSource {
  readonly stride = CANDLE_STRIDE;
  readonly head = 0;
  ints = new Int32Array(0);
  data = new Float32Array(0);
  /** Entries drawn: the non-empty source columns, then the forming bar's when it has one. */
  count = 0;
  /** Reallocations (`reserve`) since construction: a bench's allocation counter. */
  grown = 0;
  /** The last write's changed entries [from, to); patched to every node in `nodes`. */
  dirtyFrom = 0;
  dirtyTo = 0;
  readonly nodes: string[] = [];
  private readonly range = new RangeSlot();

  constructor(
    columns = 0,
    public sink: RangePatchSink | null = null,
  ) {
    this.reserve(columns);
  }

  get capacity(): number {
    return this.ints.length / CANDLE_STRIDE;
  }

  /** Room for `columns` source columns plus the forming entry; never shrinks. */
  reserve(columns: number): void {
    const n = Number.isFinite(columns) && columns > 0 ? Math.floor(columns) + 1 : 1;
    if (n <= this.capacity) return;
    this.ints = new Int32Array(n * CANDLE_STRIDE);
    this.data = new Float32Array(this.ints.buffer);
    this.grown += 1;
  }

  /**
   * The entries of `src`, then the forming bar of `store` (if its last bar is forming) at device
   * column `formingColumn`. Columns past the capacity, empty or outside [0, MAX_COLUMN] are
   * skipped, so the loop is bounded by the preallocated width, never by the bar count.
   */
  write(src: ColumnSource, store: BarStore | null = null, formingColumn = -1): number {
    const s = src.stride;
    const cap = this.capacity;
    let n = 0;
    let from = cap;
    let to = 0;
    if (s >= 4 && Number.isInteger(src.firstColumn)) {
      const v = src.ints;
      const count = Math.min(src.count, Math.floor(v.length / s), cap - 1);
      for (let j = 0; j < count; j += 1) {
        const at = j * s;
        const lo = v[at] as number;
        const hi = v[at + 1] as number;
        const col = src.firstColumn + j;
        if (lo > hi || col < 0 || col > MAX_COLUMN) continue;
        if (this.put(n, v[at + 2] as number, hi, lo, v[at + 3] as number, col)) {
          if (n < from) from = n;
          to = n + 1;
        }
        n += 1;
      }
    }
    const fc = Math.floor(formingColumn);
    if (store !== null && formingLast(store) && fc >= 0 && fc <= MAX_COLUMN && n < cap) {
      const c = store.columns;
      const p = (store.ringHead + store.length - 1) & (store.capacity - 1);
      const o = c.open[p] ?? 0; // scalars: no per-frame array
      if (this.put(n, o, c.high[p] ?? 0, c.low[p] ?? 0, c.close[p] ?? 0, fc)) {
        if (n < from) from = n;
        to = n + 1;
      }
      n += 1;
    }
    this.count = n;
    this.dirtyFrom = to > from ? from : 0;
    this.dirtyTo = to > from ? to : 0;
    if (this.sink !== null && to > from) {
      const r = this.range.set("patch", from, to, 0);
      for (let i = 0; i < this.nodes.length; i += 1) this.sink.patch(this.nodes[i] as string, r);
    }
    return n;
  }

  /** Writes entry e; true when a word changed. */
  private put(e: number, o: number, h: number, l: number, c: number, col: number): boolean {
    const w = e * CANDLE_STRIDE;
    const v = this.ints;
    const meta = (col << 4) | candleDir(o, h, l, c);
    if (v[w] === o && v[w + 1] === h && v[w + 2] === l && v[w + 3] === c && v[w + 4] === meta) {
      return false;
    }
    v[w] = o;
    v[w + 1] = h;
    v[w + 2] = l;
    v[w + 3] = c;
    v[w + 4] = meta;
    return true;
  }
}

/**
 * BQ-06 (D06 §12: L1 / L2 volume is the neutral max per column): bars [from, to) on the 26 §3.6
 * grid, bar i in device column `floor((i + 0.5 - leftIndex) · pxPerBar)`, `pxPerBar` = barSpacing
 * · dpr. `out[col - firstColumn]` = the max volume; `out` is zeroed first, columns outside it are
 * skipped. Reads the ring through its mask; no allocation. Returns the columns written.
 */
export function foldVolumeMax(
  store: BarStore,
  leftIndex: number,
  pxPerBar: number,
  from: number,
  to: number,
  firstColumn: number,
  out: Float32Array,
): number {
  out.fill(0);
  if (!(pxPerBar > 0) || !Number.isFinite(pxPerBar) || !Number.isFinite(leftIndex)) return 0;
  const vol = store.columns.volume;
  const mask = store.capacity - 1;
  const head = store.ringHead;
  const end = Math.min(Number.isFinite(to) ? Math.floor(to) : 0, store.length);
  let last = -1;
  for (let i = Math.max(0, Number.isFinite(from) ? Math.floor(from) : 0); i < end; i += 1) {
    const at = Math.floor((i + 0.5 - leftIndex) * pxPerBar) - firstColumn;
    if (at < 0 || at >= out.length) continue;
    const v = vol[(head + i) & mask] as number;
    if (v > (out[at] as number)) out[at] = v;
    if (at > last) last = at;
  }
  return last + 1;
}
