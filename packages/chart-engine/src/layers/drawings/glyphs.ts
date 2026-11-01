// The label glyph seam (E14-T03 PR 2, #358 BQ-1): what the label batch reads from an SDF atlas,
// so labels position, bound and batch now and draw real glyphs once E11-S11 (#336) lands its
// atlas behind the same interface. `FakeAtlas` is the metrics-only stand-in (texture 0: no atlas
// bound, so a WebGL2 label samples nothing until #336; the 2D path draws text with `fillText`).
// Labels are data (SR-E14-03): `clampLabel` already capped them at 120 code points with controls
// and bidi stripped; a code point the atlas lacks draws `?` (26 §3.7), so a label can never grow
// the atlas. DOM- and GL-free.

/** A glyph's words, in em (y down from the baseline) and atlas uv: `GlyphSource.glyph`'s `out`. */
export const GLYPH = {
  advance: 0,
  x0: 1,
  y0: 2,
  x1: 3,
  y1: 4,
  u0: 5,
  v0: 6,
  u1: 7,
  v1: 8,
} as const;
export const GLYPH_WORDS = 9;
/** 26 §3.7: an out-of-set character draws `?` from the same family. */
export const REPLACEMENT = 0x3f;

export interface GlyphSource {
  /** The label batch's `texture` number (26 §3.4 `GlTextures`): 0 binds none. */
  readonly texture: number;
  /** Above and below the baseline, in em: the label box's height. */
  readonly ascent: number;
  readonly descent: number;
  /** Code point `cp`'s metrics into `out[0..GLYPH_WORDS)`; false when the atlas lacks it. */
  glyph(cp: number, out: Float64Array): boolean;
}

/**
 * The stand-in atlas: printable ASCII on a 16 × 8 grid, every glyph 0.6 em wide (a monospace
 * advance), its box 0.05..0.55 em across and 0.75 em above to 0.2 em below the baseline; the
 * space advances with an empty box. Deterministic, so tests and the bench measure fixed boxes.
 */
export class FakeAtlas implements GlyphSource {
  readonly texture = 0;
  readonly ascent = 0.8;
  readonly descent = 0.2;

  glyph(cp: number, out: Float64Array): boolean {
    if (cp < 0x20 || cp > 0x7e) return false;
    const slot = cp - 0x20;
    const col = slot % 16;
    const row = (slot - col) / 16;
    const blank = cp === 0x20;
    out[GLYPH.advance] = 0.6;
    out[GLYPH.x0] = blank ? 0 : 0.05;
    out[GLYPH.y0] = blank ? 0 : -0.75;
    out[GLYPH.x1] = blank ? 0 : 0.55;
    out[GLYPH.y1] = blank ? 0 : 0.2;
    out[GLYPH.u0] = col / 16;
    out[GLYPH.v0] = row / 8;
    out[GLYPH.u1] = (col + 1) / 16;
    out[GLYPH.v1] = (row + 1) / 8;
    return true;
  }
}

/** `cp`'s metrics, else `?`'s, else an empty zero-advance glyph; never throws. */
export function glyphOf(src: GlyphSource, cp: number, out: Float64Array): void {
  if (src.glyph(cp, out) || src.glyph(REPLACEMENT, out)) return;
  out.fill(0, 0, GLYPH_WORDS);
}

/** The code point at `i` (a pair counts as one; `clampLabel` left no lone surrogate). */
export const codeAt = (s: string, i: number): number => s.codePointAt(i) as number;
export const width16 = (cp: number): number => (cp > 0xffff ? 2 : 1);

const G = new Float64Array(GLYPH_WORDS);

/** A label's advance in em and its drawn glyphs (a non-empty box), into `out` [em, glyphs]. */
export function measure(src: GlyphSource, text: string, out: Float64Array): void {
  let em = 0;
  let glyphs = 0;
  for (let i = 0; i < text.length; i += width16(codeAt(text, i))) {
    glyphOf(src, codeAt(text, i), G);
    em += G[GLYPH.advance] as number;
    if ((G[GLYPH.x1] as number) > (G[GLYPH.x0] as number)) glyphs += 1;
  }
  out[0] = em;
  out[1] = glyphs;
}
