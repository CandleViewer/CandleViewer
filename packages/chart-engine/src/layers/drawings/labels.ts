// The `drawing-label` instance ring (E14-T03 PR 2): each visible drawing's clamped label as one
// instance per drawn glyph (a space advances with none), anchored at the record's first anchor in
// chart space, so a pan or zoom rewrites nothing; the glyph boxes are device px (CSS × dpr) and
// rebuilt on DATA, STYLE or a DPR change only. Beside the glyphs it keeps one run per label (the
// anchor, offset, font px and colour) and the label strings themselves, which the Canvas 2D path
// draws with `fillText` (26 §3.7's fallback): text as data, never parsed, no CSS built from it.
// Glyph metrics come through the `GlyphSource` seam (#358 BQ-1). DOM- and GL-free.
import { attributeOffset, PROGRAM } from "../../scene/instance-layout.js";
import { codeAt, GLYPH, GLYPH_WORDS, type GlyphSource, glyphOf, width16 } from "./glyphs.js";
import type { DrawingRecord } from "./record.js";
import { attributesOf, flatten, InstanceRing } from "./ring.js";

export const LABEL_ATTRIBUTES = attributesOf(PROGRAM.drawingLabel);
export const LABEL_STRIDE = LABEL_ATTRIBUTES.stride;
const ANCHOR = attributeOffset(PROGRAM.drawingLabel, "a_anchor");
const BOX = attributeOffset(PROGRAM.drawingLabel, "a_glyph");
const UV = attributeOffset(PROGRAM.drawingLabel, "a_uv");
const COLOR = attributeOffset(PROGRAM.drawingLabel, "a_color");

/** A label's size when the style names none (CSS px, inside `FONT_MIN..FONT_MAX`). */
export const LABEL_FONT_PX = 12;
/** A non-`text` drawing's label sits this far right of and above its first anchor (CSS px). */
export const LABEL_OFFSET_PX = 4;
/**
 * A run's words (the 2D path's): the anchor ivec4 as the glyphs', then x and y offset and font
 * size in device px, one unused word, then premultiplied RGBA.
 */
export const RUN = { anchor: 0, x: 4, y: 5, font: 6, rgba: 8 } as const;
export const RUN_STRIDE = 12;

/** The label `r` draws: its clamped text, or "" when it has none or is hidden. */
export const labelOf = (r: DrawingRecord): string =>
  r.input.visible === false ? "" : (r.input.label ?? "");
/** Its font size in CSS px (`copyInput` already clamped a given one to 8..48). */
export const fontOf = (r: DrawingRecord): number => r.input.style.fontSize ?? LABEL_FONT_PX;
/** Its offset from the anchor, CSS px: a `text` drawing's baseline sits on its anchor. */
export const offsetOf = (r: DrawingRecord): number =>
  r.input.kind === "text" ? 0 : LABEL_OFFSET_PX;

const G = new Float64Array(GLYPH_WORDS);
const PREMUL = new Float64Array(4);

export class LabelInstances extends InstanceRing {
  /** One run per drawn label, `RUN_STRIDE` words each; `ints` is its int32 view. */
  runs = new Float32Array(RUN_STRIDE * 16);
  runInts = new Int32Array(this.runs.buffer);
  runCount = 0;
  /** Each run's text: the record's own clamped string (no copy). */
  readonly texts: string[] = [];

  constructor() {
    super(LABEL_STRIDE);
  }

  /** Writes every label's glyphs and run in draw order; a pan never calls this. */
  encode(order: readonly DrawingRecord[], glyphs: GlyphSource, dpr: number, opacity = 1): void {
    let total = 0;
    let runs = 0;
    for (let i = 0; i < order.length; i += 1) {
      const r = order[i] as DrawingRecord;
      const n = r.labelGlyphs;
      total += n;
      if (labelOf(r) !== "") runs += 1;
    }
    this.begin(total);
    this.reserveRuns(runs);
    let at = 0;
    let run = 0;
    for (let i = 0; i < order.length; i += 1) {
      const r = order[i] as DrawingRecord;
      const text = labelOf(r);
      if (text === "") continue;
      const size = fontOf(r) * dpr;
      const dx = offsetOf(r) * dpr;
      const dy = 0 - dx; // up by the offset (+0, never -0, for `text`)
      this.writeRun(run, r, text, dx, dy, size, opacity);
      run += 1;
      let pen = dx;
      for (let c = 0; c < text.length; c += width16(codeAt(text, c))) {
        glyphOf(glyphs, codeAt(text, c), G);
        const x0 = G[GLYPH.x0] as number;
        const x1 = G[GLYPH.x1] as number;
        if (x1 > x0) this.glyph(at++, r, pen + x0 * size, dy, size, opacity);
        pen += (G[GLYPH.advance] as number) * size;
      }
    }
    this.runCount = run;
    this.texts.length = run;
    this.end(at);
  }

  /** One glyph instance from `G`: the anchor, its box from the pen, the uv, the colour. */
  private glyph(i: number, r: DrawingRecord, x: number, y: number, size: number, op: number) {
    const o = i * LABEL_STRIDE;
    this.open();
    this.anchor(o + ANCHOR, r.idx[0] as number, r.tick[0] as number);
    this.f(o + BOX, x);
    this.f(o + BOX + 1, y + (G[GLYPH.y0] as number) * size);
    this.f(o + BOX + 2, ((G[GLYPH.x1] as number) - (G[GLYPH.x0] as number)) * size);
    this.f(o + BOX + 3, ((G[GLYPH.y1] as number) - (G[GLYPH.y0] as number)) * size);
    for (let k = 0; k < 4; k += 1) this.f(o + UV + k, G[GLYPH.u0 + k] as number);
    this.rgba(o + COLOR, r.colour, op);
    this.close(i);
  }

  private writeRun(
    k: number,
    r: DrawingRecord,
    text: string,
    dx: number,
    dy: number,
    size: number,
    opacity: number,
  ): void {
    const o = k * RUN_STRIDE;
    const idx = r.idx[0] as number;
    const tick = r.tick[0] as number;
    const ix = Math.min(2 ** 30, Math.max(-(2 ** 30), Math.floor(idx)));
    const it = Math.min(2 ** 30, Math.max(-(2 ** 30), Math.floor(tick)));
    this.runInts[o] = ix;
    this.runInts[o + 1] = it;
    this.runs[o + 2] = Math.abs(idx - ix) < 1 ? idx - ix : 0;
    this.runs[o + 3] = Math.abs(tick - it) < 1 ? tick - it : 0;
    this.runs[o + RUN.x] = dx;
    this.runs[o + RUN.y] = dy;
    this.runs[o + RUN.font] = size;
    this.runs[o + 7] = 0;
    flatten(r.colour, opacity, PREMUL);
    for (let c = 0; c < 4; c += 1) this.runs[o + RUN.rgba + c] = PREMUL[c] as number;
    this.texts[k] = text;
  }

  /** Grows the run table to hold `n` runs (doubling: none once warm). */
  private reserveRuns(n: number): void {
    if (n * RUN_STRIDE <= this.runs.length) return;
    let cap = this.runs.length / RUN_STRIDE;
    while (cap < n) cap *= 2;
    this.runs = new Float32Array(cap * RUN_STRIDE);
    this.runInts = new Int32Array(this.runs.buffer);
  }
}
