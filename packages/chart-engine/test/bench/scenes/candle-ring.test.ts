// The clock-free half of the `candle-ring` scene (E12-S06): counts and zero allocation.
import { describe, expect, it } from "vitest";
import { CandleRingBench } from "../../../bench/scenes/candle-ring.js";

describe("candle-ring bench: a live feed into store and ring at 5k and 100k bars, zero alloc", () => {
  it.each([5_000, 100_000])(
    "%i bars, 1 000 steps: 2 patches per mutation, nothing reallocated",
    (size) => {
      const bench = new CandleRingBench(size);
      const [patches, written] = [bench.patches, bench.ring.written];
      for (let s = 0; s < 1_000; s += 1) bench.step();
      expect(bench.allocationsInMutationPath).toBe(0);
      expect([bench.patches - patches, bench.ring.written - written]).toEqual([4_000, 2_000]);
      expect([bench.store.length, bench.ring.length]).toEqual([size, size]);
    },
  );
});
