// The price gutter's width (E11-S06, README BQ-201, BQ-202; E11-D02 §6): the widest label the
// pane's format can produce plus 8 px, at least 48 px, re-measured only when the format, the
// decimals, the font or the magnitude class changes (`engine.axis.gutter_remeasures`), never per
// frame. Text is measured through the `TextMeasure` seam: until E11-S11's atlas metrics land,
// `fixedMeasure` stands in with tabular numerals at a fixed advance.
import { formatNumber } from "./format.js";
import { PRICE_KIND } from "./price-ticks.js";

export interface TextMeasure {
  /** Width of `text` in CSS px. */
  width(text: string): number;
  /** The label box height in CSS px. */
  readonly height: number;
}

/** BQ-202's stand-in: compact 11 px, a 0.6 em advance, a 1.2 line box. */
export const fixedMeasure = (fontPx = 11, advanceEm = 0.6): TextMeasure => ({
  width: (text) => text.length * fontPx * advanceEm,
  height: Math.round(fontPx * 1.2),
});

export const GUTTER_PAD_PX = 8;
export const GUTTER_MIN_PX = 48;

export class GutterCache {
  /** The current width, CSS px; 0 until a pane has a format. */
  width = 0;
  remeasures = 0;
  private readonly key = new Float64Array([-1, -1, -1]);
  private measure: TextMeasure | null = null;

  /** The gutter for (kind, decimals, magnitude class) measured with `m`. */
  widthFor(kind: number, decimals: number, magnitude: number, m: TextMeasure): number {
    const k = this.key;
    if (k[0] === kind && k[1] === decimals && k[2] === magnitude && this.measure === m) {
      return this.width;
    }
    k[0] = kind;
    k[1] = decimals;
    k[2] = magnitude;
    this.measure = m;
    this.remeasures += 1;
    // The widest label of the class: every digit a 9, plus the sign and mark of a percentage.
    const nines = formatNumber(10 ** (Math.max(0, magnitude) + 1) - 10 ** -decimals, decimals);
    const sample = kind === PRICE_KIND.percent ? `+${nines}%` : nines;
    this.width = Math.max(GUTTER_MIN_PX, Math.ceil(m.width(sample)) + GUTTER_PAD_PX);
    return this.width;
  }
}
