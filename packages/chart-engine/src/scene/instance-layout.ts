// Per-program instance layouts (E11-T05, README BQ-87): how each instance of a program's batch
// sits in its node's `VertexSource` slot, so the WebGL2 backend (its shaders' `in` attributes)
// and the Canvas2D backend (its painters) read one ring the same way. DOM- and GL-free.

/** A batch's `program` number: the state-sort key of 26 §3.1, shared by both backends. */
export const PROGRAM = { line: 0, quad: 1, sdfText: 2, barCell: 3 } as const;

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
];

/** The float offset of `name` in `program`'s slot (a module-load lookup, never per frame). */
export function attributeOffset(program: number, name: string): number {
  const a = INSTANCE_LAYOUTS[program]?.attributes.find(([n]) => n === name);
  if (a === undefined) throw new Error(`chart-engine: program ${program} has no ${name}`);
  return a[1];
}
