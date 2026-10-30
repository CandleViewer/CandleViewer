// The counted half of the `pan-zero-upload` scene (E11-S01 PR3, B1-like); timing is in the
// .perf.test.ts. The upload count is on a fake sink until E11-S02's GL backend (BQ-S12).
import { describe, expect, it } from "vitest";
import { PanZeroUploadBench } from "../../../bench/scenes/pan-zero-upload.js";
import { FakeGl } from "../../gl/fake-gl.js";

describe("Scenario: Panning reuses GPU buffers", () => {
  it("5 s of pan over 100 000 bars marks TRANSFORM, never DATA, and uploads nothing", () => {
    const bench = new PanZeroUploadBench(100_000);
    const batch = bench.builder.drawList[0];
    expect([bench.builder.uploads, batch?.count]).toEqual([1, 100_000]); // the first build: all

    for (let f = 1; f <= 300; f += 1) bench.step(f * (5000 / 300)); // 60 Hz for 5 s
    expect([bench.transformCollects, bench.dataDirtyCollects]).toEqual([300, 0]);
    // The AC's bufferSubData count over the pan: still the one upload of the first build.
    expect([bench.builder.uploads, bench.allocationsInFramePath]).toEqual([1, 0]);
    expect([bench.builder.drawCount, bench.builder.drawList[0]]).toEqual([1, batch]);
    expect([bench.requests, bench.scheduler.parked]).toEqual([301, true]); // parks between pans
  });
});

describe("Scenario: Panning does not touch GPU buffers", () => {
  it("a 200 px pan through ChartViewport on the fake GL writes uniforms only (BQ-79)", () => {
    const gl = new FakeGl();
    const bench = new PanZeroUploadBench(100_000, () => 0, gl);
    expect(gl.writes).toEqual([`full ${100_000 * 4 * 4}`]); // the first build's one upload
    const [at, uploads, start] = [gl.log.length, bench.builder.uploads, bench.viewport.timeStart];
    bench.step(16, 200);
    const frame = gl.log.slice(at);
    expect(gl.writes).toHaveLength(1);
    expect(bench.builder.uploads).toBe(uploads);
    expect(frame.filter((c) => /^buffer/.test(c))).toEqual([]);
    expect(frame.filter((c) => /^uniform/.test(c))).toEqual([
      "uniform1i",
      "uniform1i",
      "uniform4f",
      "uniform2f",
    ]);
    expect(frame).toContain("drawArraysInstanced");
    expect(start - bench.viewport.timeStart).toBeCloseTo((200 / 6) * 60e6, 0); // 200 px of 6 px bars
    expect(bench.allocationsInFramePath).toBe(0);
  });
});
