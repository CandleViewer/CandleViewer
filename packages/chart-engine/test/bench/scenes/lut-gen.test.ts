// `lut-gen` scene (E11-T04 PR-3): what each step does, counted, not timed.
import { describe, expect, it } from "vitest";
import { benchThemes, LutGenBench } from "../../../bench/scenes/lut-gen.js";
import { LUT_BYTES, LUT_ROW_BYTES } from "../../../src/theme/ColorLut.js";

describe("lut-gen bench scene", () => {
  it("cycles six seeded themes (three names × two conventions), deterministically", () => {
    const a = benchThemes();
    expect(a.map((t) => `${t.name}/${t.convention}`)).toEqual([
      "dark/standard",
      "dark/inverted",
      "light/standard",
      "light/inverted",
      "high-contrast/standard",
      "high-contrast/inverted",
    ]);
    expect(benchThemes()[2]?.slots).toEqual(a[2]?.slots);
  });

  it("every step rewrites the one buffer it owns: no new buffer per switch", () => {
    const bench = new LutGenBench();
    const first = Uint8Array.from(bench.step());
    expect(bench.step()).toBe(bench.pixels);
    expect(bench.pixels).not.toEqual(first); // the inverted twin swaps the intensity rows
    expect(bench.pixels.length).toBe(LUT_BYTES);
    expect(bench.switches).toBe(2);
  });

  it("stepOne writes only its own row", () => {
    const bench = new LutGenBench();
    bench.stepOne("ask");
    const rows = [0, 1, 2].map((r) =>
      bench.pixels.subarray(r * LUT_ROW_BYTES, (r + 1) * LUT_ROW_BYTES).some((b) => b !== 0),
    );
    expect(rows).toEqual([false, true, false]);
    bench.stepOne("bid");
    bench.stepOne("delta");
    expect(bench.pixels.subarray(2 * LUT_ROW_BYTES).some((b) => b !== 0)).toBe(true);
  });
});
