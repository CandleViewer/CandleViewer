// The clock-free half of the `candle-series` scene (E12-S06): two draws per frame, a pan uploads
// nothing, a feed frame uploads the two touched bars once (not per part), no allocation.
import { describe, expect, it } from "vitest";
import { CandleSeriesBench } from "../../../bench/scenes/candle-series.js";
import { FakeGl } from "../../gl/fake-gl.js";

describe("candle-series bench: 5k and 100k bars, pan and feed frames", () => {
  it.each([5_000, 100_000])("%i bars: 2 draws, 0 pan bytes, one sub-upload per feed", (n) => {
    const gl = new FakeGl();
    const bench = new CandleSeriesBench(n, gl);
    const trace = bench.backend.trace;
    bench.backend.takeUploadedBytes();
    for (let f = 1; f <= 60; f += 1) bench.pan(f * 16);
    expect([trace.draws, bench.backend.takeUploadedBytes()]).toEqual([2, 0]);
    const writes = gl.writes.length;
    for (let f = 61; f <= 120; f += 1) bench.feed(f * 16);
    expect(trace.draws).toBe(2);
    expect(gl.writes.length - writes).toBe(60); // one bufferSubData per frame for both parts
    expect(bench.backend.takeUploadedBytes()).toBe(60 * 2 * 20); // the patched and the new bar
    expect(bench.allocationsSinceWarm).toBe(0);
  });
});
