// The clock-free half of the `volume-ring` scene (E12-S08 pre-stage): counts and zero allocation.
import { describe, expect, it } from "vitest";
import { VolumeRingBench } from "../../../bench/scenes/volume-ring.js";

describe("volume-ring bench: a live feed into store and volume ring, zero alloc", () => {
  it.each([5_000, 100_000])(
    "%i bars, 1 000 steps: 1 patch per mutation, nothing reallocated",
    (size) => {
      const bench = new VolumeRingBench(size);
      const [patches, written] = [bench.patches, bench.series.ring.written];
      for (let s = 0; s < 1_000; s += 1) bench.step();
      expect(bench.allocationsInMutationPath).toBe(0);
      expect([bench.patches - patches, bench.series.ring.written - written]).toEqual([
        2_000, 2_000,
      ]);
      expect([bench.store.length, bench.series.ring.length]).toEqual([size, size]);
    },
  );
});
