// E11-S09 (BQ-3): the share normalisation, property-tested with seeded loops (fast-check is not
// installed): every share positive, in proportion to its weight, and the shares summed left to
// right equal 1 exactly ("cannot sum to 0.999"), for any pane count up to the protocol's limit.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { defaultWeight, normaliseShares } from "../../src/scene/pane-shares.js";
import { PANE_LIMIT } from "../../src/worker/protocol.js";

const SEEDS = Array.from({ length: 40 }, (_, i) => 446_000 + i);

/** n weights in [1e-9, 1]: uniform, tiny or a mix, so rounding has room to drift. */
function weights(next: () => number, n: number): number[] {
  const kind = Math.floor(next() * 3);
  return Array.from({ length: n }, () => {
    const u = 0.001 + 0.999 * next(); // [0.001, 1)
    if (kind === 0) return u;
    if (kind === 1) return u * 1e-6;
    return next() < 0.5 ? u : u * 1e-4;
  });
}

describe("Scenario: pane shares always sum to exactly 1 (BQ-3)", () => {
  it("test_normaliseShares_seededWeights_positiveProportionalAndSumExactlyOne", () => {
    for (const seed of SEEDS) {
      const next = mulberry32(seed);
      for (let round = 0; round < 50; round += 1) {
        const n = 1 + Math.floor(next() * PANE_LIMIT);
        const w = weights(next, n);
        const out: number[] = [];
        normaliseShares(w, n, out);
        let sum = 0;
        for (const s of out) sum += s;
        expect(sum, `seed ${seed} round ${round}`).toBe(1);
        expect(
          out.every((s) => s > 0 && s <= 1),
          `seed ${seed}`,
        ).toBe(true);
        const total = w.reduce((a, b) => a + b, 0);
        for (let i = 0; i < n - 1; i += 1) {
          expect(out[i]).toBeCloseTo((w[i] as number) / total, 12);
        }
      }
    }
  });

  it("test_normaliseShares_oneOrNone_writesOneOrNothing", () => {
    const out: number[] = [];
    normaliseShares([], 0, out);
    expect(out).toEqual([]);
    normaliseShares([0.3], 1, out);
    expect(out).toEqual([1]);
    normaliseShares([Number.MIN_VALUE, 1], 2, out); // a degenerate weight still gets a share
    expect(out[0]).toBeGreaterThan(0);
    expect((out[0] as number) + (out[1] as number)).toBe(1);
  });

  it("test_defaultWeight_existingWeights_theMeanSoTheNewPaneGetsAnEqualShare", () => {
    expect(defaultWeight([], 0)).toBe(1);
    const w = [0.2, 0.2, 0.2];
    const mean = defaultWeight(w, 3);
    const out: number[] = [];
    normaliseShares([...w, mean], 4, out);
    expect(out.map((s) => s.toFixed(12))).toEqual(Array(4).fill((0.25).toFixed(12)));
  });
});
