import { describe, expect, it, vi } from "vitest";
import { SceneA } from "../../../bench/scenes/scene-a.mjs";
import { buildDriverScript } from "../../../bench/driver.mjs";
import { generateM0Fixture } from "../../../bench/fixtures/index.mjs";

// Scoped to this file only: 100k-bar fixture generation is slow under v8 coverage
// instrumentation (vitest 3). Wall-clock budgets are not asserted here (this project runs under
// coverage); they live in scene-a.perf.test.ts. #3578
vi.setConfig({ testTimeout: 60_000 });

describe("SceneA (E06-K02 throwaway prototype) — BenchScene conformance + budgets", () => {
  it("processes only the visible window plus prefetch margin, not the full store", () => {
    const fixture = generateM0Fixture({ seed: 1, barCount: 100_000 });
    const scene = new SceneA();
    scene.init(fixture);
    scene.step(0, { tMs: 0, kind: "none" });
    const stats = scene.extendedStats();
    // Default viewport (barSpacing=6, plotWidth=1600) shows ~267 bars; with a
    // 50-bar prefetch margin either side that is well under 1000, nowhere
    // near the 100k total.
    expect(stats.barsTouched).toBeLessThan(1000);
    expect(stats.barsTouched).toBeGreaterThan(0);
    scene.dispose();
  });

  it("static-frame work does not scale with total bar count: 10k vs 100k (timing: scene-a.perf.test.ts)", () => {
    // Both stores show the same visible window (viewport math is independent of total store
    // length), so the counted work per frame is identical; the 10% frame-time claim is timed in
    // the perf file.
    const work = (barCount: number) => {
      const scene = new SceneA();
      scene.init(generateM0Fixture({ seed: 1, barCount }));
      scene.step(0, { tMs: 0, kind: "none" });
      const { barsTouched, currentLod, drawCalls, bufferBytesUploaded } = scene.extendedStats();
      scene.dispose();
      return { barsTouched, currentLod, drawCalls, bufferBytesUploaded };
    };
    expect(work(100_000)).toEqual(work(10_000));
  });

  it("exposes currentLod in stats() per US-CHART-001 (aggregation level indicated)", () => {
    const fixture = generateM0Fixture({ seed: 1, barCount: 1000 });
    const scene = new SceneA();
    scene.init(fixture);
    scene.step(0, { tMs: 0, kind: "none" });
    expect(["L0", "L1", "L2"]).toContain(scene.extendedStats().currentLod);
    scene.dispose();
  });

  it("B1: continuous pan issues <= 8 draw calls on every frame (timing: scene-a.perf.test.ts)", () => {
    const scene = new SceneA();
    scene.init(generateM0Fixture({ seed: 42, barCount: 100_000 }));
    let mostDrawCalls = 0;
    for (const event of buildDriverScript({ scenario: "B1", durationMs: 5000 })) {
      scene.step(event.tMs, event);
      mostDrawCalls = Math.max(mostDrawCalls, scene.stats().drawCalls);
    }
    scene.dispose();
    expect(mostDrawCalls).toBeLessThanOrEqual(8);
  });

  it("B2: LOD level changes over a full 0.1->50 px/bar sweep stay within the hysteresis budget (<=6)", () => {
    const fixture = generateM0Fixture({ seed: 42, barCount: 100_000 });
    const scene = new SceneA();
    scene.init(fixture);
    for (let i = 0; i <= 300; i += 1) {
      const tMs = (i / 300) * 20_000;
      const progress = tMs / 20_000;
      const pxPerBar = 0.1 + progress * (50 - 0.1);
      scene.step(tMs, { tMs, kind: "zoom", payload: { pxPerBar } });
    }
    expect(scene.lodChanges).toBeLessThanOrEqual(6);
    scene.dispose();
  });

  it("parks with zero allocation counter when idle (render-on-demand contract)", () => {
    const fixture = generateM0Fixture({ seed: 1, barCount: 1000 });
    const scene = new SceneA();
    scene.init(fixture);
    scene.step(0, { tMs: 0, kind: "none" });
    expect(scene.extendedStats().allocationsInFramePath).toBe(0);
    scene.dispose();
  });
});
