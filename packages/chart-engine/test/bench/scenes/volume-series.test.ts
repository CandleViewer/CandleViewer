// The clock-free half of the `volume-series` scene (E12-S08, BQ-13): one `volume` draw per frame
// labelled `series.volume.body` (<= 40 draws), a pan uploads nothing, a feed frame uploads the two
// touched bars once, no allocation past warm-up.
import { describe, expect, it } from "vitest";
import { VolumeSeriesBench } from "../../../bench/scenes/volume-series.js";
import { FakeGl } from "../../gl/fake-gl.js";

describe("volume-series bench: 5k and 100k bars, pan and feed frames", () => {
  it.each([5_000, 100_000])(
    "%i bars: 1 draw (<= 40), 0 pan bytes, one sub-upload per feed",
    (n) => {
      const gl = new FakeGl();
      gl.trackDraws = true;
      const bench = new VolumeSeriesBench(n, gl);
      const { trace } = bench.backend;
      trace.enabled = true;
      bench.backend.takeUploadedBytes();
      for (let f = 1; f <= 60; f += 1) bench.pan(f * 16);
      expect(trace.draws).toBe(1);
      expect(trace.draws).toBeLessThanOrEqual(40);
      expect(trace.labels).toEqual(["series.volume.body"]);
      expect(bench.backend.takeUploadedBytes()).toBe(0);
      expect(gl.draws.slice(-1)).toEqual([`4 ${bench.series.ring.capacity}`]);
      const writes = gl.writes.length;
      for (let f = 61; f <= 120; f += 1) bench.feed(f * 16);
      expect(trace.draws).toBe(1);
      expect(gl.writes.length - writes).toBe(60);
      expect(bench.backend.takeUploadedBytes()).toBe(60 * 2 * 20);
      expect(bench.allocationsSinceWarm).toBe(0);
    },
  );
});
