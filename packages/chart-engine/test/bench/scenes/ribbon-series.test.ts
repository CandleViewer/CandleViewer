// The clock-free half of the `ribbon-series` scene (E12-S07 PR B): line 3 draws, area 4, baseline
// 6 per frame (plan §3, within the 18 per pane), each over every ring slot (the shader collapses
// the empty ones) except the one-instance last disc and base line; a pan uploads nothing (B and
// the parts are uniforms); a feed frame uploads the one new slot once (not per part); no
// allocation. The VAOs bind this slot and the next one (the +1 instance read).
import { describe, expect, it } from "vitest";
import { RibbonSeriesBench } from "../../../bench/scenes/ribbon-series.js";
import { RIBBON_GEOM, type RibbonKind } from "../../../src/layers/index.js";
import { FakeGl } from "../../gl/fake-gl.js";

const DRAWS: Record<RibbonKind, readonly string[]> = {
  line: ["stroke", "join", "last"],
  area: ["fill", "stroke", "join", "last"],
  baseline: ["above", "below", "base", "stroke", "join", "last"],
};

describe("ribbon-series bench: 5k and 100k bars, pan and feed frames", () => {
  for (const kind of ["line", "area", "baseline"] as const) {
    it.each([5_000, 100_000])(`%i ${kind} bars: ${DRAWS[kind].length} draws, 0 pan bytes`, (n) => {
      const gl = new FakeGl();
      gl.trackDraws = true;
      const bench = new RibbonSeriesBench(n, gl, () => 0, kind, 600);
      const { trace } = bench.backend;
      trace.enabled = true;
      bench.backend.takeUploadedBytes();
      const writes = gl.writes.length;
      for (let f = 1; f <= 60; f += 1) bench.pan(f * 16);
      expect([trace.draws, bench.backend.takeUploadedBytes(), gl.writes.length]).toEqual([
        DRAWS[kind].length,
        0,
        writes,
      ]);
      expect(trace.labels).toEqual(DRAWS[kind].map((p) => `series.${kind}.${p}`));
      const cap = bench.ring.capacity;
      const ones = new Set(["last", "base"]);
      expect(gl.draws.slice(-DRAWS[kind].length)).toEqual(
        DRAWS[kind].map((p) => `4 ${ones.has(p) ? 1 : cap}`),
      );
      for (let f = 61; f <= 120; f += 1) bench.feed(f * 16);
      expect(trace.draws).toBe(DRAWS[kind].length);
      expect(gl.writes.length - writes).toBe(60); // one bufferSubData per frame for every part
      expect(bench.backend.takeUploadedBytes()).toBe(60 * 20); // the one new slot
      expect(bench.allocationsSinceWarm).toBe(0);
    });
  }

  it("the six VAOs bind this slot and the next (stride 20 bytes, +20 for the next slot)", () => {
    const gl = new FakeGl();
    new RibbonSeriesBench(5_000, gl, () => 0, "baseline", 600);
    const per = [
      "attrib 0 4 20 0",
      "divisor 0 1",
      "attrib 1 1 20 16",
      "divisor 1 1",
      "attrib 2 4 20 20",
      "divisor 2 1",
      "attrib 3 1 20 36",
      "divisor 3 1",
    ];
    expect(gl.attribs).toEqual(Array.from({ length: 6 }, () => per).flat());
  });

  it("at the spacing floor (L2): x snaps to device-pixel columns, still 0 pan bytes", () => {
    const gl = new FakeGl();
    const bench = new RibbonSeriesBench(100_000, gl, () => 0, "area");
    bench.backend.takeUploadedBytes();
    for (let f = 1; f <= 30; f += 1) bench.pan(f * 16);
    expect(bench.series.geom[RIBBON_GEOM.l2]).toBe(1);
    expect([bench.backend.trace.draws, bench.backend.takeUploadedBytes()]).toEqual([4, 0]);
    expect(bench.allocationsSinceWarm).toBe(0);
  });
});
