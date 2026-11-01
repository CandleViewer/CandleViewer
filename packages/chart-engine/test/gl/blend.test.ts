// E14-T03 PR 2: premultiplied blending on the GL fake. The drawings programs (`drawing-line`,
// `drawing-fill`, `drawing-label`) write premultiplied colour (the flatten opacity, BQ-4), so they
// draw with BLEND on and `blendFunc(ONE, ONE_MINUS_SRC_ALPHA)`; every older program draws with
// BLEND off, as before this PR (the candle's colours are opaque, the grid's straight), switched
// only where the program run changes; the backend keeps the state across frames (off on a new or
// restored context, WebGL's default), so a chart without drawings makes no blend call at all. The
// candle and 2D parity suites run unchanged beside this.
import { describe, expect, it } from "vitest";
import { DrawingsDragBench } from "../../bench/scenes/drawings-drag.js";
import { GLBackend } from "../../src/gl/backend.js";
import { GL } from "../../src/gl/gl-types.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { INSTANCE_LAYOUTS, PROGRAM } from "../../src/scene/instance-layout.js";
import { FakeGl } from "./fake-gl.js";

const PREMUL = `${GL.ONE} ${GL.ONE_MINUS_SRC_ALPHA}`;
const batch = (nodeId: string, program: number): RetainedBatch => ({
  ...{ nodeId, program, texture: 0, first: 0, count: 2 },
  ...{ layer: 0, seq: 0, lo: 0, hi: 2 },
});

/** A backend with one 2-instance ring per program in `programs`, and their batches in order. */
function frameOf(programs: readonly number[]) {
  const gl = new FakeGl();
  gl.trackDraws = true;
  const backend = new GLBackend(gl, null);
  const list = programs.map((p, i) => {
    const stride = INSTANCE_LAYOUTS[p]?.stride ?? 4;
    backend.attach(`n${i}`, { data: new Float32Array(2 * stride), head: 0, stride });
    return batch(`n${i}`, p);
  });
  return { gl, backend, list };
}
const calls = (gl: FakeGl, name: string): number => gl.log.filter((c) => c === name).length;

describe("premultiplied blending (E14-T03 PR 2)", () => {
  it("the drawings frame draws all three batches blended, ONE / ONE_MINUS_SRC_ALPHA", () => {
    const gl = new FakeGl();
    gl.trackDraws = true;
    new DrawingsDragBench(1_000, 358, new GLBackend(gl, null));
    expect(gl.draws).toHaveLength(3);
    expect(gl.draws.every((d) => d.endsWith(" blend"))).toBe(true);
    expect([gl.blendFn, calls(gl, "enable"), calls(gl, "disable")]).toEqual([PREMUL, 1, 0]);
  });

  it("candle, then the drawings, then a grid line: BLEND off, on once, off again", () => {
    const { gl, backend, list } = frameOf([
      PROGRAM.candle,
      PROGRAM.drawingLine,
      PROGRAM.drawingFill,
      PROGRAM.drawingLabel,
      PROGRAM.line,
    ]);
    expect(backend.submit(list, list.length, 100, 100)).toBeNull();
    expect(gl.draws).toEqual(["4 2", "4 2 blend", "4 2 blend", "4 2 blend", "4 2"]);
    expect([calls(gl, "enable"), calls(gl, "disable"), calls(gl, "blendFunc")]).toEqual([1, 1, 1]);
    expect(gl.blendFn).toBe(PREMUL);
  });

  it("frames of the older programs alone make no blend call at all", () => {
    const { gl, backend, list } = frameOf([PROGRAM.line, PROGRAM.quad, PROGRAM.candle]);
    for (let f = 0; f < 3; f += 1) backend.submit(list, list.length, 100, 100);
    expect(gl.draws.every((d) => !d.endsWith(" blend"))).toBe(true);
    expect([calls(gl, "enable"), calls(gl, "disable"), calls(gl, "blendFunc")]).toEqual([0, 0, 0]);
  });

  it("the state carries across frames, and a restored context starts from BLEND off", () => {
    const { gl, backend, list } = frameOf([PROGRAM.drawingLine]);
    for (let f = 0; f < 3; f += 1) backend.submit(list, list.length, 100, 100);
    expect([calls(gl, "enable"), calls(gl, "blendFunc")]).toEqual([1, 1]); // once, not per frame
    gl.loseContext();
    backend.invalidate();
    gl.restoreContext();
    gl.blending = false; // what a restored context has
    expect(backend.restore()).toBe(true);
    backend.submit(list, list.length, 100, 100);
    expect([calls(gl, "enable"), gl.draws.at(-1)]).toEqual([2, "4 2 blend"]);
  });
});
