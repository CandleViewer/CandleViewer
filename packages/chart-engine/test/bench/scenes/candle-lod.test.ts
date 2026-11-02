// The clock-free half of the `candle-lod` scene (E12-S09 PR 1, BQ-07 / BQ-12): 5k / 50k / 100k
// bars × L0 / L1 / L2, two draws per frame at every tier (D06 §5.5), no allocation past warm-up.
// L0 / L1 pans upload nothing; an L2 pan re-folds and uploads only the entries that changed; a
// forming-bar tick uploads one instance (20 B) at every tier: at L2 its own entry, never a column.
import { describe, expect, it } from "vitest";
import { CandleLodBench } from "../../../bench/scenes/candle-lod.js";
import { CANDLE_PART } from "../../../src/layers/index.js";
import { FakeGl } from "../../gl/fake-gl.js";

const ROWS = [5_000, 50_000, 100_000].flatMap((n) =>
  ([0, 1, 2] as const).map((t) => [n, t] as const),
);

describe("candle-lod bench: tiers × sizes", () => {
  it.each(ROWS)("%i bars at L%i: 2 draws, the pan and tick uploads, no allocation", (n, tier) => {
    const gl = new FakeGl();
    gl.trackDraws = true;
    const bench = new CandleLodBench(n, gl, tier);
    const { backend, entries } = bench;
    backend.takeUploadedBytes();
    for (let f = 1; f <= 30; f += 1) bench.pan(f * 16);
    expect(backend.trace.draws).toBe(2);
    const pan = backend.takeUploadedBytes();
    if (tier < 2) expect(pan).toBe(0);
    else expect(pan).toBeLessThanOrEqual(30 * entries.count * 20);
    for (let f = 31; f <= 60; f += 1) bench.tick(f * 16);
    expect(backend.trace.draws).toBe(2);
    expect(backend.takeUploadedBytes()).toBe(30 * 20); // the forming bar alone, every tick
    const parts = bench.series.blocks.slice(0, 2).map((b) => b.ints[0]);
    expect(parts).toEqual(
      tier === 2
        ? [CANDLE_PART.columnWick, CANDLE_PART.columnSpan]
        : [CANDLE_PART.wick, CANDLE_PART.body],
    );
    if (tier === 2) {
      expect(entries.count).toBeGreaterThan(1_000); // ~one entry a device column, + the forming
      expect(gl.draws.slice(-2)).toEqual([`4 ${entries.count}`, `4 ${entries.count}`]);
    }
    expect(bench.allocationsSinceWarm).toBe(0);
  });
});
