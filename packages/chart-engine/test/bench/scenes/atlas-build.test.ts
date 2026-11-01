// `atlas-build` / `atlas-cache` scenes (E11-S11 PR A): what each step does, counted, not timed.
import { describe, expect, it } from "vitest";
import { AtlasCacheBench, buildAtlas } from "../../../bench/scenes/atlas-build.js";
import { ATLAS_CONFIG } from "../../../src/text/config.js";

describe("atlas bench scenes", () => {
  it("atlas-build packs 194 glyphs into packed rows near K01's 150–192 KiB record", () => {
    const img = buildAtlas();
    expect(img.metrics.length / 8).toBe(194);
    expect(img.rows.byteLength).toBe(ATLAS_CONFIG.width * img.usedHeight);
    expect(img.rows.byteLength).toBeLessThan(256 * 1024);
  });

  it("atlas-cache decodes its record on every step", () => {
    const bench = new AtlasCacheBench();
    expect([bench.step(), bench.step()]).toEqual([true, true]);
  });
});
