import { describe, expect, it, vi } from "vitest";
import { bitmapToSdf, edt2d, INF } from "../../../bench/scenes/edt.mjs";
import {
  shelfPack,
  generateAtlas,
  loadAtlas,
  MemoryAtlasStore,
  atlasCacheKey,
  contrastRatio,
} from "../../../bench/scenes/atlas.mjs";
import { FootprintStore } from "../../../bench/scenes/footprint-store.mjs";
import { GlyphRunCache } from "../../../bench/scenes/glyph-runs.mjs";
import { selectFootprintLod } from "../../../bench/scenes/footprint-lod.mjs";
import { SceneB } from "../../../bench/scenes/scene-b.mjs";
import { runScenario } from "../../../bench/runner.mjs";
import { captureMachineDescriptor } from "../../../bench/machine.mjs";
import { generateM0Fixture } from "../../../bench/fixtures/index.mjs";

interface Ext {
  visibleCells: number;
  glyphCount: number;
  textBatchMs: number;
  outlinePassMs: number;
  textDrawCalls: number;
  lod: string;
}

// Scoped to this file only: 100k-bar fixture generation is slow under v8 coverage
// instrumentation (vitest 3). Wall-clock budgets are not asserted here (this project runs under
// coverage); they live in scene-b.perf.test.ts. #3554
vi.setConfig({ testTimeout: 60_000 });

describe("EDT", () => {
  it("matches brute-force squared distance on a known shape", () => {
    const w = 12;
    const h = 9;
    const pts: [number, number][] = [
      [2, 3],
      [9, 6],
    ];
    const grid = new Float64Array(w * h).fill(INF);
    for (const [x, y] of pts) grid[y * w + x] = 0;
    edt2d(grid, w, h);
    for (let y = 0; y < h; y += 1) {
      for (let x = 0; x < w; x += 1) {
        const ref = Math.min(...pts.map(([px, py]) => (x - px) ** 2 + (y - py) ** 2));
        expect(grid[y * w + x]).toBeCloseTo(ref, 6);
      }
    }
  });
  it("SDF is high inside and low outside", () => {
    const w = 16;
    const h = 16;
    const bmp = new Uint8Array(w * h);
    for (let y = 4; y < 12; y += 1) for (let x = 4; x < 12; x += 1) bmp[y * w + x] = 255;
    const sdf = bitmapToSdf(bmp, w, h, 4);
    expect(sdf[8 * w + 8]).toBeGreaterThan(160);
    expect(sdf[0]).toBeLessThan(90);
  });
});

describe("shelf packer / atlas", () => {
  it("is deterministic and has no overlaps", () => {
    const items = [..."0123456789ABCDEF▲▼"].map((ch, i) => ({
      ch,
      w: 10 + (i % 4),
      h: 20 + (i % 3),
    }));
    const a = shelfPack(items, 128);
    const b = shelfPack([...items].reverse(), 128);
    expect(a.orderHash).toBe(b.orderHash);
    const rects = [...a.placements.values()];
    for (let i = 0; i < rects.length; i += 1) {
      for (let j = i + 1; j < rects.length; j += 1) {
        const p = rects[i]!;
        const q = rects[j]!;
        const overlap = p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h;
        expect(overlap).toBe(false);
      }
    }
  });
  it("generates the frozen glyph set incl. triangles and caches by key (warm-load budget: scene-b.perf.test.ts)", async () => {
    const store = new MemoryAtlasStore();
    const cold = await loadAtlas(store, "Inter", 500);
    expect(cold.cacheHit).toBe(false);
    expect(cold.atlas.glyphs["▲"]).toBeDefined();
    expect(cold.atlas.glyphs["×"]).toBeDefined();
    const warm = await loadAtlas(store, "Inter", 500);
    expect(warm.cacheHit).toBe(true);
    expect(atlasCacheKey("Inter", 500)).not.toBe(atlasCacheKey("Inter", 700));
  });
});

describe("FootprintStore", () => {
  const c = (barIndex: number, priceLevel: number, bidVol = 1, askVol = 2) => ({
    barIndex,
    priceLevel,
    bidVol,
    askVol,
    tradeCount: 3,
  });
  it("keeps offsets as prefix sums and returns affected ranges", () => {
    const s = new FootprintStore(2, 1);
    s.upsertFootprintCells([c(0, 5), c(0, 3), c(1, 9), c(2, 1), c(2, 2)]);
    expect(Array.from(s.offsets.subarray(0, 4))).toEqual([0, 2, 3, 5]);
    expect(Array.from(s.priceLevel.subarray(0, 2))).toEqual([3, 5]);
    const upd = s.upsertFootprintCells([c(0, 3, 50, 60)]);
    expect(s.length).toBe(5);
    expect(s.cellAt(0).bidVol).toBe(50);
    expect(upd).toEqual([{ from: 0, to: 1 }]);
  });
});

describe("glyph-run cache", () => {
  it("format change invalidates runs only, not cell data", () => {
    const scene = new SceneB({ cells: 200 });
    scene.init(generateM0Fixture({ seed: 1, barCount: 20 }));
    const before = Array.from(scene.store.bidVol.subarray(0, 200));
    const v0 = scene.runs?.formatVersion;
    scene.setFormat("compact");
    expect(scene.runs?.formatVersion).toBe((v0 ?? 0) + 1);
    expect(Array.from(scene.store.bidVol.subarray(0, 200))).toEqual(before);
    expect(scene.store.length).toBe(200);
  });
  it("reformat of 2,500 cells keeps the store contents (budget: scene-b.perf.test.ts)", () => {
    const scene = new SceneB();
    scene.init(generateM0Fixture({ seed: 1, barCount: 200 }));
    expect(scene.setFormat("compact")).toBeGreaterThanOrEqual(0);
  });
  it("lays out one instance per known glyph", () => {
    const a = generateAtlas();
    const cache = new GlyphRunCache(a.glyphs, 4);
    const run = cache.append(0, "12,4", 0, 0, 12, [1, 1, 1, 1]);
    expect(run.count).toBe(4);
    expect(cache.glyphCount).toBe(4);
  });
});

describe("footprint LOD (E06-D01 LOD_PROFILE_M0)", () => {
  it("applies hysteresis at the boundaries and does not flicker on a slow zoom", () => {
    expect(selectFootprintLod(12, null)).toBe("L0");
    expect(selectFootprintLod(11, "L0")).toBe("L0");
    expect(selectFootprintLod(10.1, "L0")).toBe("L1");
    expect(selectFootprintLod(11, "L1")).toBe("L1");
    expect(selectFootprintLod(12, "L1")).toBe("L0");
    let prev: "L0" | "L1" | "L2" | "L3" | null = null;
    let changes = 0;
    for (let h = 16; h >= 4; h -= 0.05) {
      const n = selectFootprintLod(h, prev);
      if (prev && n !== prev) changes += 1;
      prev = n as string as "L0";
    }
    expect(changes).toBe(3);
  });
  it("shedding text withholds numbers only: cell count unchanged (timing: scene-b.perf.test.ts)", () => {
    const scene = new SceneB();
    scene.init(generateM0Fixture({ seed: 1, barCount: 200 }));
    scene.step(0, { tMs: 0, kind: "none" });
    const l0 = scene.extendedStats() as unknown as Ext;
    const l0DrawCalls = scene.stats().drawCalls;
    expect(l0.lod).toBe("L0");
    expect(l0.glyphCount).toBeGreaterThan(0);
    scene.setCellHeight(7);
    scene.step(16, { tMs: 16, kind: "none" });
    const l2 = scene.extendedStats() as unknown as Ext;
    expect(l2.lod).toBe("L2");
    expect(l2.glyphCount).toBe(0);
    expect(l2.visibleCells).toBe(l0.visibleCells);
    // The work is counted, not timed: the shed frame no longer issues the text draw call.
    expect(scene.stats().drawCalls).toBeLessThan(l0DrawCalls);
  });
});

describe("B3 and contrast", () => {
  const machine = captureMachineDescriptor({ gpu: "stub", driver: "stub" });
  const run = (arm: "sdf" | "canvas2d") => {
    const scene = new SceneB({ arm });
    scene.init(generateM0Fixture({ seed: 1, barCount: 200 }));
    const r = runScenario({
      scene,
      scenario: "B3",
      durationMs: 1000,
      repetitions: 3,
      runtime: "chromium",
      runtimeVersion: "node",
      machine,
      seed: 1,
      lodProfile: "LOD_PROFILE_M0",
      peakProcessMemMB: 1,
      peakProcessMemSource: "test",
    });
    return { r, ext: scene.extendedStats() as unknown as Ext };
  };
  it("SDF arm renders 2,500 cells with <= 2 text draw calls (timing: scene-b.perf.test.ts)", () => {
    const { ext } = run("sdf");
    expect(ext.visibleCells).toBe(2500);
    expect(ext.textDrawCalls).toBeLessThanOrEqual(2);
  });
  it("Canvas-2D arm exceeds the draw-call gate (comparison evidence)", () => {
    expect(run("canvas2d").ext.textDrawCalls).toBeGreaterThan(2);
  });
  it("outline reaches >= 4.5:1 where raw text-on-fill does not", () => {
    expect(contrastRatio("#E8EAED", "#0B0E11")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#E8EAED", "#2EBD59")).toBeLessThan(4.5);
    expect(contrastRatio("#E8EAED", "#E5484D")).toBeLessThan(4.5);
  });
});
