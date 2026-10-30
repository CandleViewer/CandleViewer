// The clock-free half of the `bar-store` mutation microbench (E11-T03); timing is in .perf.test.ts.
import { describe, expect, it } from "vitest";
import { BarStoreBench } from "../../../bench/scenes/bar-store-mutations.js";

describe("bar-store bench: append / patch / prepend at 100k and 200k, zero alloc", () => {
  it.each([
    [100_000, 3_003, 0], // below maxBars: append, patch and prepend each step (warm-up included)
    [200_000, 2_002, 1_001], // at maxBars: append evicts one, patch; no prepend
  ])("%i bars, 1 000 steps: %i mutations, %i evictions", (size, mutations, evictions) => {
    const bench = new BarStoreBench(size);
    for (let s = 0; s < 1_000; s += 1) bench.step();
    expect(bench.allocationsInMutationPath).toBe(0);
    expect([bench.mutations, bench.store.counters.evictions]).toEqual([mutations, evictions]);
  });
});
