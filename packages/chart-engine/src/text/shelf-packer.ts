// Deterministic shelf packing (E11-K01 BQ-183, BQ-263): height descending, then codepoint, then
// slot; `pad` px between glyphs. The atlas never grows at runtime (E14 DR8): an overflow is null,
// which the atlas reports as `ENGINE_ATLAS_GENERATION_FAILED` (`overflow`).
export interface PackItem {
  readonly w: number;
  readonly h: number;
  readonly cp: number;
}

export interface Packed {
  /** Top-left corner per item, in input order. */
  readonly x: Int32Array;
  readonly y: Int32Array;
  /** Rows used from the top: the packed-rows record holds only these (K01 BQ-176). */
  readonly usedHeight: number;
  /** Glyph pixels over the whole texture, in percent (`engine.atlas.occupancy_pct`). */
  readonly occupancyPct: number;
}

export function shelfPack(
  items: readonly PackItem[],
  width: number,
  height: number,
  pad: number,
): Packed | null {
  const order = items.map((_, i) => i);
  const it = (i: number): PackItem => items[i] as PackItem;
  order.sort((a, b) => it(b).h - it(a).h || it(a).cp - it(b).cp || a - b);
  const xs = new Int32Array(items.length);
  const ys = new Int32Array(items.length);
  let [x, y, shelf, ink] = [0, 0, 0, 0];
  // An index loop, not `for...of`: Semgrep folds `of` into `in`, so an indexed write in a
  // `for...of` reads as a keyed copy to cv-engine-proto-pollution (E11-X02, F-15).
  for (let k = 0; k < order.length; k += 1) {
    const i = order[k] as number;
    const { w, h } = it(i);
    if (w > width) return null;
    if (x + w > width) {
      y += shelf + pad;
      x = 0;
      shelf = 0;
    }
    if (y + h > height) return null;
    xs[i] = x;
    ys[i] = y;
    x += w + pad;
    shelf = Math.max(shelf, h);
    ink += w * h;
  }
  return { x: xs, y: ys, usedHeight: y + shelf, occupancyPct: (100 * ink) / (width * height) };
}
