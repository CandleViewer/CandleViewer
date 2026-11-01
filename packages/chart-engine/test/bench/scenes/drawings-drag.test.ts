// The counted `drawings-drag` scene (E14-T03 slice 1, B8 skeleton), Scenario 1's isolation: a drag
// re-indexes one record and never updates the price or footprint stand-ins; a pan re-indexes none.
import { describe, expect, it } from "vitest";
import {
  DRAG_FRAMES,
  DrawingsDragBench,
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

  it("one drawing-line draw a frame (26 §3.10's drawings budget is 3); every line-type instance", () => {
    const { backend, bench } = gpu();
    expect(bench.drawings.lines.count).toBe(LINE_INSTANCES);
    expect([backend.trace.draws, backend.trace.triangles]).toEqual([1, 2 * LINE_INSTANCES]);
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
    expect(gl.uniforms.length - uniforms).toBe(100 * 5); // u_viewport, the bases, u_k, u_log
    expect(backend.trace.draws).toBe(1);
  });

  it("a 180-frame drag uploads one 64-byte instance a frame, at the dragged drawing's slot", () => {
    const { gl, bench } = gpu();
    const from = gl.writes.length;
    bench.run();
    // d8 is the fifth line-type record (d0..d3 draw one each; d4..d7 are fills and text).
    expect(gl.writes.slice(from)).toEqual(Array.from({ length: 180 }, () => "sub 256 64 16"));
  });

  it("a DPR change re-encodes the widths once: one upload of every instance", () => {
    const { gl, bench } = gpu();
    const from = gl.writes.length;
    bench.viewport.setSize(1920, 1080, 2);
    bench.graph.markTheme(); // what the runtime marks on a DPR change (BQ-152)
    bench.frame();
    expect(gl.writes.slice(from)).toEqual([`sub 0 0 ${16 * LINE_INSTANCES}`]);
  });
});
