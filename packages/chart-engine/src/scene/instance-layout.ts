// Per-program instance layouts (E11-T05, README BQ-87): how each instance of a program's batch
// sits in its node's `VertexSource` slot, so the WebGL2 backend (its shaders' `in` attributes)
// and the Canvas2D backend (its painters) read one ring the same way. DOM- and GL-free.

/** A batch's `program` number: the state-sort key of 26 §3.1, shared by both backends. */
export const PROGRAM = {
  line: 0,
  quad: 1,
  sdfText: 2,
  barCell: 3,
  candle: 4,
  drawingLine: 5,
  drawingFill: 6,
  drawingLabel: 7,
} as const;

/** [shader attribute, float offset in the slot, components, read as int32 bits]. */
export type InstanceAttribute = readonly [name: string, offset: number, size: number, int: boolean];

export interface InstanceLayout {
  /** Floats per instance; a source's `stride` may be larger, never smaller. */
  readonly stride: number;
  readonly attributes: readonly InstanceAttribute[];
}

/**
 * Indexed by `PROGRAM`. `line` and `quad` are device px with y up (the shaders' `u_viewport`
 * divide); `bar-cell` is (bar index, tick) as int32 bits, its size in bars and ticks, through the
 * pane block (BQ-75); colours are RGBA in 0..1.
 */
export const INSTANCE_LAYOUTS: readonly InstanceLayout[] = [
  {
    stride: 9,
    attributes: [
      ["a_segment", 0, 4, false],
      ["a_width", 4, 1, false],
      ["a_color", 5, 4, false],
    ],
  },
  {
    stride: 8,
    attributes: [
      ["a_rect", 0, 4, false],
      ["a_color", 4, 4, false],
    ],
  },
  {
    stride: 8,
    attributes: [
      ["a_rect", 0, 4, false],
      ["a_uv", 4, 4, false],
    ],
  },
  {
    stride: 8,
    attributes: [
      ["a_cell", 0, 2, true],
      ["a_size", 2, 2, false],
      ["a_color", 4, 4, false],
    ],
  },
  {
    // E12-S06 `candle`: the CandleRing's int32 [open, high, low, close] ticks and its meta word
    // (flags | dir << 4); colour comes from the palette uniforms, never the ring.
    stride: 5,
    attributes: [
      ["a_ohlc", 0, 4, true],
      ["a_meta", 4, 1, true],
    ],
  },
  // E14-T03 `drawing-line`, every attribute an ivec4 at location = its row (the VAO binds ints
  // only): each anchor (bar index, tick, then the float bits of their fractions); style float
  // bits (width in device px, dash index, extend: 0 none / 1 forward / 2 both, direction 0..2);
  // colour float bits, RGBA in 0..1. The shader unpacks floats with intBitsToFloat.
  {
    stride: 16,
    attributes: [
      ["a_anchor0", 0, 4, true],
      ["a_anchor1", 4, 4, true],
      ["a_style", 8, 4, true],
      ["a_color", 12, 4, true],
    ],
  },
  // E14-T03 `drawing-fill`, ivec4s as `drawing-line`'s: corners A, B, C (D = B + C − A in the
  // shader); fill and stroke RGBA float bits; style float bits (kind 0 rect / 1 ellipse / 2
  // band, stroke width in device px, dash index, unused).
  {
    stride: 24,
    attributes: [
      ["a_cornerA", 0, 4, true],
      ["a_cornerB", 4, 4, true],
      ["a_cornerC", 8, 4, true],
      ["a_fill", 12, 4, true],
      ["a_stroke", 16, 4, true],
      ["a_style", 20, 4, true],
    ],
  },
  // E14-T03 `drawing-label` (PR 2), ivec4s as `drawing-line`'s: the label's anchor; the glyph box
  // float bits (x, y, width, height in device px from the projected anchor, y down); its atlas uv
  // (u0, v0, u1, v1) float bits; colour float bits, premultiplied RGBA in 0..1.
  {
    stride: 16,
    attributes: [
      ["a_anchor", 0, 4, true],
      ["a_glyph", 4, 4, true],
      ["a_uv", 8, 4, true],
      ["a_color", 12, 4, true],
    ],
  },
];

/** The float offset of `name` in `program`'s slot (a module-load lookup, never per frame). */
export function attributeOffset(program: number, name: string): number {
  const a = INSTANCE_LAYOUTS[program]?.attributes.find(([n]) => n === name);
  if (a === undefined) throw new Error(`chart-engine: program ${program} has no ${name}`);
  return a[1];
}
