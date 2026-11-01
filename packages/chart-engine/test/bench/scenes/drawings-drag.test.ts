// The counted `drawings-drag` scene (E14-T03 slice 1, B8 skeleton), Scenario 1's isolation: a drag
// re-indexes one record and never updates the price or footprint stand-ins; a pan re-indexes none.
import { describe, expect, it } from "vitest";
import {
  DRAG_FRAMES,
  DrawingsDragBench,
  FILL_INSTANCES,
  LABEL_GLYPHS,
  LINE_INSTANCES,
} from "../../../bench/scenes/drawings-drag.js";
import { GLBackend } from "../../../src/gl/backend.js";
import { FakeGl } from "../../gl/fake-gl.js";

describe("Scenario: Dragging a drawing does not touch the price layer (counted)", () => {
  it("200 drawings + 50 order lines over 100 000 bars: one record per drag frame", () => {
    const bench = new DrawingsDragBench();
    expect([bench.drawings.set.size, bench.drawings.reindexed]).toEqual([250, 250]);
    bench.run();
    expect(bench.drawings.reindexed).toBe(250 + DRAG_FRAMES);
    expect(bench.drawings.boundsPasses).toBe(1 + DRAG_FRAMES);
    expect([bench.price.updates, bench.footprint.updates]).toEqual([1, 1]);
    bench.pan(-30);
    expect(bench.drawings.reindexed).toBe(250 + DRAG_FRAMES);
    expect([bench.price.updates, bench.footprint.updates]).toEqual([2, 2]);
  });
});

describe("drawings-drag on the GL fake (slice 2): uniforms-only pan, one-instance drag", () => {
  const gpu = () => {
    const gl = new FakeGl();
    const backend = new GLBackend(gl, null);
    return { gl, backend, bench: new DrawingsDragBench(100_000, 358, backend) };
  };

  it("three draws a frame, lines, fills and labels (26 §3.10's drawings budget is 3)", () => {
    const { backend, bench } = gpu();
    expect(bench.drawings.lines.count).toBe(LINE_INSTANCES);
    expect(bench.drawings.fills.count).toBe(FILL_INSTANCES);
    expect(bench.drawings.labels.count).toBe(LABEL_GLYPHS);
    const instances = LINE_INSTANCES + FILL_INSTANCES + LABEL_GLYPHS;
    expect([backend.trace.draws, backend.trace.triangles]).toEqual([3, 2 * instances]);
  });

  it("100 pans: no buffer write, no re-encode, the ring kept; the pane block is rewritten", () => {
    const { gl, backend, bench } = gpu();
    const writes = gl.writes.length;
    const ring = bench.drawings.lines.data;
    const [encodes, uniforms] = [bench.drawings.encodes, gl.uniforms.length];
    for (let f = 0; f < 100; f += 1) bench.pan(-3);
    expect([gl.writes.length, bench.drawings.encodes]).toEqual([writes, encodes]);
    expect([bench.drawings.lines.data === ring, backend.takeUploadedBytes() > 0]).toEqual([
      true,
      true, // the first frame's full upload, and nothing since
    ]);
    // u_viewport, the bases, u_k, u_log: per program (line, fill, label), per frame.
    expect(gl.uniforms.length - uniforms).toBe(100 * 3 * 5);
    expect(backend.trace.draws).toBe(3);
  });

  it("a 180-frame drag uploads d8's segment and its label's 6 glyphs a frame, nothing else", () => {
    const { gl, bench } = gpu();
    const from = gl.writes.length;
    bench.run();
    // d8's segment is line instance 10: d0..d3 draw one each, d4's rect 4, d6's band 2; its label
    // ("level 8": 6 glyphs) follows its anchor, glyphs 48..53 after d0..d7's 6 each.
    const frame = ["sub 640 160 16", `sub ${48 * 64} ${48 * 16} ${6 * 16}`];
    expect(gl.writes.slice(from)).toEqual(Array.from({ length: 180 }, () => frame).flat());
  });

  it("a DPR change re-encodes the widths once: one upload of every instance", () => {
    const { gl, bench } = gpu();
    const from = gl.writes.length;
    bench.viewport.setSize(1920, 1080, 2);
    bench.graph.markTheme(); // what the runtime marks on a DPR change (BQ-152)
    bench.frame();
    expect(gl.writes.slice(from)).toEqual([
      `sub 0 0 ${16 * LINE_INSTANCES}`,
      `sub 0 0 ${24 * FILL_INSTANCES}`, // the fills' ring widths too
      `sub 0 0 ${16 * LABEL_GLYPHS}`, // and every glyph box (device px)
    ]);
  });
});
