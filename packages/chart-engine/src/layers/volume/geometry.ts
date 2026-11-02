// The volume column twin (E12-S08, E12-D06 §12): the float64 CPU copy of one column the `volume`
// program draws from a `VolumeRing` instance, for the 2D painter, hit-testing and the tests,
// line for line with `src/gl/shaders/volume.ts`. The column is the candle body's width and
// centre, from the tick-0 line to the volume line, at FULL height whatever the bar's direction
// (a doji or zero-range bar is a full column; the candle's 2-hairline mark is not applied). Colour
// is the real direction at L0 (up: tinted fill with outline, down: solid, doji / zero-range:
// neutral wick) and neutral wick at a decimated tier. An unavailable bar, and zero volume, yield
// w = 0. `maxPerColumn` is the decimated tier's reduction (D06 §12 L1 / L2). No DOM.
import { GEOM } from "../candle/geometry.js";
import { PALETTE } from "../candle/palette.js";
import { CANDLE_DIR, MARK } from "../candle/ring.js";

/** `meta >> 4`: bit 2 = unavailable (meta bit 6), bit 3 = neutral tier (meta bit 7). */
export const MARK_UNAVAILABLE = 4;
export const MARK_NEUTRAL = 8;

export const unavailableMark = (mark: number): boolean => (mark & MARK_UNAVAILABLE) !== 0;
export const neutralMark = (mark: number): boolean =>
  (mark & MARK_NEUTRAL) !== 0 || (mark & MARK.dir) >= CANDLE_DIR.doji;

/** The `u_palette` row of a column from `meta >> 4`: up, down; doji, zero-range, a tier: wick. */
export function volumeColor(mark: number): number {
  if (neutralMark(mark)) return PALETTE.wick;
  return (mark & MARK.dir) === CANDLE_DIR.up ? PALETTE.up : PALETTE.down;
}

/** True when the column is outlined with its interior tinted: an up column at L0 (D06 §12). */
export const volumeTinted = (mark: number): boolean =>
  !neutralMark(mark) && (mark & MARK.dir) === CANDLE_DIR.up;

/**
 * Column of bar `index` as [x, y, w, h] in `u_viewport` px (y down) into `out`. `ticks` is the
 * instance's word 0 (volume in ticks), `mark` its `meta >> 4`; the pane block (`k`, bases) is the
 * volume pane's, whose zero maps to the pane bottom; `geom` the series' `u_geom`.
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
  if (unavailableMark(mark)) {
    out[0] = out[1] = out[2] = out[3] = 0;
    return;
  }
  const hair = geom[GEOM.hair] ?? 1;
  const body = geom[GEOM.body] ?? 1;
  const centre = (index - indexBase + 0.5 - (k[3] ?? 0)) * (k[0] ?? 0);
  const y0 = (ticks - tickBase) * (k[1] ?? 0) + (k[2] ?? 0);
  const y1 = (0 - tickBase) * (k[1] ?? 0) + (k[2] ?? 0);
  const top = Math.min(y0, y1);
  out[0] = Math.floor(centre - body * 0.5 + 0.5);
  out[1] = top;
  out[2] = body;
  out[3] = ticks === 0 ? 0 : Math.max(Math.max(y0, y1) - top, hair);
}

/**
 * The decimated tier's reduction (D06 §12 L1 / L2: the maximum volume per column, neutral):
 * groups of `per` consecutive instances of `ticks` / `metas` (the ring's word 0 and meta, in
 * logical order) into `out`; an unavailable bar does not count, and a column with none yields
 * -1 (unavailable). Returns the column count. E12-S09 owns the tier's column placement; this is
 * the reduction it calls.
 */
export function maxPerColumn(
  ticks: ArrayLike<number>,
  metas: ArrayLike<number>,
  per: number,
  out: Int32Array,
): number {
  const n = ticks.length;
  const step = Math.max(1, Math.floor(per));
  let c = 0;
  for (let i = 0; i < n; i += step) {
    let max = -1;
    const end = Math.min(n, i + step);
    for (let j = i; j < end; j += 1) {
      if (unavailableMark((metas[j] as number) >> 4)) continue;
      if ((ticks[j] as number) > max) max = ticks[j] as number;
    }
    out[c] = max;
    c += 1;
  }
  return c;
}
