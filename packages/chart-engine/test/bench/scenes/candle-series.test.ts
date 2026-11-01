// The clock-free half of the `candle-series` scene (E12-S06): two draws per frame (candles, and
// OHLC as stem + 10-vertex ticks or, at the floor, the candle mark), a pan uploads nothing, a
// feed frame uploads the two touched bars once (not per part), no allocation.
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

  it.each([5_000, 100_000])("%i OHLC bars, 120 in view: stem + ticks, the same uploads", (n) => {
    const gl = new FakeGl();
    gl.trackDraws = true;
    const bench = new CandleSeriesBench(n, gl, () => 0, "bars", 120);
    const { trace } = bench.backend;
    trace.enabled = true;
    bench.backend.takeUploadedBytes();
    for (let f = 1; f <= 60; f += 1) bench.pan(f * 16);
    const cap = bench.ring.capacity;
    expect([trace.draws, bench.backend.takeUploadedBytes()]).toEqual([2, 0]);
    expect(gl.draws.slice(-2)).toEqual([`4 ${cap}`, `10 ${cap}`]);
    expect(trace.labels).toEqual(["series.ohlc.stem", "series.ohlc.ticks"]);
    expect(trace.triangles).toBe(2 * cap + 8 * cap);
    const writes = gl.writes.length;
    for (let f = 61; f <= 120; f += 1) bench.feed(f * 16);
    expect(trace.draws).toBe(2);
    expect(gl.writes.length - writes).toBe(60);
    expect(bench.backend.takeUploadedBytes()).toBe(60 * 2 * 20);
    expect(bench.allocationsSinceWarm).toBe(0);
  });

  it("OHLC at the spacing floor draws the candle mark: two 4-vertex draws", () => {
    const gl = new FakeGl();
    gl.trackDraws = true;
    const bench = new CandleSeriesBench(5_000, gl, () => 0, "bars");
    bench.pan(16);
    const cap = bench.ring.capacity;
    expect(gl.draws.slice(-2)).toEqual([`4 ${cap}`, `4 ${cap}`]);
  });
});

describe("candle-series bench: a theme switch", () => {
  it("re-resolves the palette with no upload and still draws twice", () => {
    const gl = new FakeGl();
    const bench = new CandleSeriesBench(5_000, gl);
    bench.backend.takeUploadedBytes();
    const writes = gl.writes.length;
    for (let f = 1; f <= 40; f += 1) bench.switchTheme(f * 16);
    expect([gl.writes.length - writes, bench.backend.takeUploadedBytes()]).toEqual([0, 0]);
    expect([bench.backend.trace.draws, bench.allocationsSinceWarm]).toEqual([2, 0]);
  });
});
