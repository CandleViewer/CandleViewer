// E14-T03 slices 2-3 on real-GL terms: `drawing-line`'s and `drawing-fill`'s vertex inputs, their
// VAO bindings on the GL fake, and the program table every backend indexes (`PROGRAM`,
// `PROGRAMS`, `INSTANCE_LAYOUTS`, `PROGRAM_VERTICES`, `PAINTERS`, `PROGRAM_PREMULTIPLIED`) staying
// aligned: `candle` is 4, `drawing-line` 5, `drawing-fill` 6 and (PR 2) `drawing-label` 7.
import { describe, expect, it } from "vitest";
import { DrawingsDragBench } from "../../bench/scenes/drawings-drag.js";
import { PAINTERS } from "../../src/canvas2d/painters.js";
import { GLBackend } from "../../src/gl/backend.js";
import { PROGRAMS } from "../../src/gl/program-cache.js";
import { DRAWING_FILL } from "../../src/gl/shaders/drawing-fill.js";
import { DASH_LUT, DRAWING_LINE } from "../../src/gl/shaders/drawing-line.js";
import { DRAWING_LABEL } from "../../src/gl/shaders/drawing-label.js";
import { PROGRAM_PREMULTIPLIED, PROGRAM_VERTICES } from "../../src/gl/submit.js";
import { FILL_ATTRIBUTES } from "../../src/layers/drawings/fills.js";
import { LABEL_ATTRIBUTES } from "../../src/layers/drawings/labels.js";
import { LINE_ATTRIBUTES } from "../../src/layers/drawings/lines.js";
import { INSTANCE_LAYOUTS, PROGRAM } from "../../src/scene/instance-layout.js";
import { FakeGl } from "./fake-gl.js";

const DASHED = [
  ["drawing-line", PROGRAM.drawingLine, DRAWING_LINE, LINE_ATTRIBUTES],
  ["drawing-fill", PROGRAM.drawingFill, DRAWING_FILL, FILL_ATTRIBUTES],
] as const;
const CASES = [
  ...DASHED,
  ["drawing-label", PROGRAM.drawingLabel, DRAWING_LABEL, LABEL_ATTRIBUTES],
] as const;

describe("the drawings programs' vertex inputs", () => {
  it.each(CASES)("%s: every `in` has a matching layout(location) row, all ivec4", (_, id, src) => {
    const layout = INSTANCE_LAYOUTS[id];
    const declared = [...src.vertex.matchAll(/^layout\(location = (\d+)\) in (\w+) (\w+);$/gm)].map(
      (m) => [Number(m[1]), m[2], m[3]],
    );
    expect(src.vertex.match(/^\s*in /gm)).toBeNull(); // no input without a location
    expect(declared).toEqual(layout?.attributes.map(([name], i) => [i, "ivec4", name]));
    expect(layout?.attributes.every(([, , size, int]) => size === 4 && int)).toBe(true);
    expect(src.vertex).toContain("gl_VertexID"); // the corner: no corner buffer is bound
  });

  it.each(DASHED)("%s: its DASH table is DASH_LUT, entry for entry", (_, _id, src) => {
    const glsl = /const vec2 DASH\[3\] = vec2\[3\]\((.*)\);/.exec(src.vertex)?.[1] ?? "";
    const entries = [...glsl.matchAll(/vec2\(([\d.]+), ([\d.]+)\)/g)].map((m) => [
      Number(m[1]),
      Number(m[2]),
    ]);
    expect(entries).toEqual(DASH_LUT.map((e) => [...e]));
  });

  it("the GL fake sees one vertexAttribIPointer + divisor 1 per input of all three programs", () => {
    const gl = new FakeGl();
    new DrawingsDragBench(1_000, 358, new GLBackend(gl, null));
    const want = [LINE_ATTRIBUTES, FILL_ATTRIBUTES, LABEL_ATTRIBUTES].flatMap((l) =>
      l.ints.flatMap(([at, offset, size]) => [
        `attrib ${at} ${size} ${l.stride * 4} ${offset * 4}`,
        `divisor ${at} 1`,
      ]),
    );
    expect(gl.attribs).toEqual(want);
    expect(want).toHaveLength(2 * (4 + 6 + 4));
  });
});

describe("the program table", () => {
  const kebab = (k: string): string => k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

  it("PROGRAMS[PROGRAM[k]].name is k for every key; every table has one row per program", () => {
    for (const [k, id] of Object.entries(PROGRAM)) expect(PROGRAMS[id]?.name, k).toBe(kebab(k));
    expect(Object.keys(PROGRAM)).toHaveLength(PROGRAMS.length);
    const tables = [PROGRAM_VERTICES, INSTANCE_LAYOUTS, PAINTERS, PROGRAM_PREMULTIPLIED];
    expect(tables.map((t) => t.length)).toEqual(Array(4).fill(PROGRAMS.length));
    const drawings = [PROGRAM.drawingLine, PROGRAM.drawingFill, PROGRAM.drawingLabel];
    expect([PROGRAM.candle, ...drawings]).toEqual([4, 5, 6, 7]);
    // Premultiplied blending is the drawings' alone: every older program draws as before.
    expect(PROGRAMS.map((_, id) => PROGRAM_PREMULTIPLIED[id])).toEqual(
      PROGRAMS.map((_, id) => (drawings as number[]).includes(id)),
    );
  });
});
