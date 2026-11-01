// E14-T03 slice 2 on real-GL terms: `drawing-line`'s vertex inputs, its VAO bindings on the GL
// fake, and the program table every backend indexes (`PROGRAM`, `PROGRAMS`, `INSTANCE_LAYOUTS`,
// `PROGRAM_VERTICES`, `PAINTERS`) staying aligned now that `candle` is 4 and `drawing-line` 5.
import { describe, expect, it } from "vitest";
import { DrawingsDragBench } from "../../bench/scenes/drawings-drag.js";
import { PAINTERS } from "../../src/canvas2d/painters.js";
import { GLBackend } from "../../src/gl/backend.js";
import { PROGRAMS } from "../../src/gl/program-cache.js";
import { DRAWING_LINE } from "../../src/gl/shaders/drawing-line.js";
import { PROGRAM_VERTICES } from "../../src/gl/submit.js";
import { LINE_ATTRIBUTES } from "../../src/layers/drawings/lines.js";
import { INSTANCE_LAYOUTS, PROGRAM } from "../../src/scene/instance-layout.js";
import { FakeGl } from "./fake-gl.js";

const LAYOUT = INSTANCE_LAYOUTS[PROGRAM.drawingLine];

describe("drawing-line's vertex inputs", () => {
  it("every `in` has a layout(location) matching its INSTANCE_LAYOUTS row, all ivec4", () => {
    const vertex = DRAWING_LINE.vertex;
    const declared = [...vertex.matchAll(/^layout\(location = (\d+)\) in (\w+) (\w+);$/gm)].map(
      (m) => [Number(m[1]), m[2], m[3]],
    );
    expect(vertex.match(/^\s*in /gm)).toBeNull(); // no input without a location
    expect(declared).toEqual(LAYOUT?.attributes.map(([name], i) => [i, "ivec4", name]));
    expect(LAYOUT?.attributes.every(([, , size, int]) => size === 4 && int)).toBe(true);
    expect(vertex).toContain("gl_VertexID"); // the corner: no corner buffer is bound
  });

  it("the GL fake sees one vertexAttribIPointer + divisor 1 per input, as the layout says", () => {
    const gl = new FakeGl();
    new DrawingsDragBench(1_000, 358, new GLBackend(gl, null));
    const stride = (LAYOUT?.stride ?? 0) * 4;
    const want = LINE_ATTRIBUTES.ints.flatMap(([at, offset, size]) => [
      `attrib ${at} ${size} ${stride} ${offset * 4}`,
      `divisor ${at} 1`,
    ]);
    expect(gl.attribs).toEqual(want);
    expect(want).toHaveLength(8);
  });
});

describe("the program table", () => {
  const kebab = (k: string): string => k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

  it("PROGRAMS[PROGRAM[k]].name is k for every key; every table has one row per program", () => {
    for (const [k, id] of Object.entries(PROGRAM)) expect(PROGRAMS[id]?.name, k).toBe(kebab(k));
    expect(Object.keys(PROGRAM)).toHaveLength(PROGRAMS.length);
    expect([PROGRAM_VERTICES, INSTANCE_LAYOUTS, PAINTERS].map((t) => t.length)).toEqual(
      Array(3).fill(PROGRAMS.length),
    );
    expect([PROGRAM.candle, PROGRAM.drawingLine]).toEqual([4, 5]);
  });
});
