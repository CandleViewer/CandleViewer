// The counted half of the `hit-pick` scene (E11-S08, BQ-141); timing is the .perf.test.ts.
import { describe, expect, it } from "vitest";
import { HitPickBench } from "../../../bench/scenes/hit-pick.js";

describe("Scenario: Picking meets the hard budget at the specified density (counted)", () => {
  // 1 000 brute-force reference scans per case (up to 1 M precise tests): a long unit test.
  const long = { timeout: 30_000 };
  it.each([250, 1_000])("%i objects: no pick reads a quarter of them; no rebuild", long, (n) => {
    const bench = new HitPickBench(n);
    bench.run();
    expect(bench.index.size).toBe(n);
    expect(bench.hits).toBeGreaterThan(100);
    expect(bench.maxCandidates).toBeLessThan(n / 4); // never a linear scan over all N
    expect(bench.index.counters.indexRebuilds).toBe(0);
    expect(bench.index.counters.candidatesTested).toBeGreaterThan(0);
    for (let i = 0; i < 1_000; i += 1) expect(bench.agrees(i), `pick ${i}`).toBe(true);
  });
});
