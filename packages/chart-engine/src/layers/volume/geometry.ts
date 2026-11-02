// The volume column twin (E12-S08 pre-stage, E12-D06 §12): the float64 CPU copy of one column
// the `candle` program's body part draws from a `VolumeRing` instance, for the 2D painter,
// hit-testing and the tests. Colour is the real direction (up, down; doji and zero-range
// neutral); the up body is the tinted fill with outline, the down body solid (D06 §6), both
// from the candle palette rows. A doji column keeps its full height here (the 2-hairline doji
// mark is a candle's, not a column's). An unavailable bar yields w = 0. No DOM.
import { candleRect, CANDLE_PART } from "../candle/geometry.js";
import { PALETTE } from "../candle/palette.js";
import { CANDLE_DIR, MARK } from "../candle/ring.js";
import { UNAVAILABLE_TICK, VOLUME_UNAVAILABLE } from "./volume-ring.js";

/** `meta >> 4` of an instance: its direction mark and the unavailable bit (meta bit 6 → 4). */
export const unavailableMark = (mark: number): boolean => (mark & (VOLUME_UNAVAILABLE >> 4)) !== 0;

/** The `u_palette` row a column is drawn in, from `meta >> 4`: up, down, else neutral (wick). */
export function volumeColor(mark: number): number {
  const dir = mark & MARK.dir;
  return dir === CANDLE_DIR.up ? PALETTE.up : dir === CANDLE_DIR.down ? PALETTE.down : PALETTE.wick;
}

/** True when the column is outlined and its interior tinted (up): D06 §6 fill + outline. */
export const volumeTinted = (mark: number): boolean => (mark & MARK.dir) === CANDLE_DIR.up;

/**
 * Column of bar `index` as [x, y, w, h] in `u_viewport` px (y down) into `out`. `ticks` is the
 * instance's close word (volume in ticks, or `UNAVAILABLE_TICK`); the pane block (`k`, bases) is
 * the volume pane's, whose zero maps to the pane bottom. `geom` is the series' `u_geom`.
 */
export function volumeRect(
  index: number,
  ticks: number,
  mark: number,
  k: ArrayLike<number>,
  indexBase: number,
  tickBase: number,
  geom: ArrayLike<number>,
  out: Float64Array,
): void {
  if (ticks === UNAVAILABLE_TICK || unavailableMark(mark)) {
    out[0] = 0;
    out[1] = 0;
    out[2] = 0;
    out[3] = 0;
    return;
  }
  // The body part with a column's mark: up or down placement (never the doji mark).
  const m = (mark & MARK.dir) === CANDLE_DIR.down ? CANDLE_DIR.down : CANDLE_DIR.up;
  candleRect(CANDLE_PART.body, index, 0, ticks, 0, ticks, m, k, indexBase, tickBase, geom, out);
}
