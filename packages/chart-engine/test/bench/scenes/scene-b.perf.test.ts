// Wall-clock budget assertions. Run ONLY by `vitest --project perf` (no coverage):
// V8 coverage instrumentation inflates timings. See docs/plan/26-chart-engine-design.md.
import { describe, expect, it } from "vitest";
import { SceneB } from "../../../bench/scenes/scene-b.mjs";
import { MemoryAtlasStore, loadAtlas } from "../../../bench/scenes/atlas.mjs";
import { runScenario } from "../../../bench/runner.mjs";
import { captureMachineDescriptor } from "../../../bench/machine.mjs";
import { generateM0Fixture } from "../../../bench/fixtures/index.mjs";
import { percentile } from "../../../bench/stats.mjs";

interface Ext {
  textBatchMs: number;
  outlinePassMs: number;
  residualMs?: number;
}

// Comparisons below use the median of an odd number of samples (nearest-rank p50 is then exact), so
// one stalled sample (GC, a preempted runner) cannot flip them. #3554 was a single-pair compare
// (4.09 ms vs 3.88 ms) that failed on a loaded runner. percentile() is typed `number | undefined`
// under noUncheckedIndexedAccess; NaN fails every comparison, so it can never pass vacuously.
const median = (xs: number[]): number => percentile(xs, 50) ?? Number.NaN;
const LOD_PAIRS = 15;
const WARM_LOADS = 5;

describe("perf budgets: SceneB", () => {
  it("reformat of 2,500 cells stays within a generous multiple of the 4 ms budget", () => {
    const scene = new SceneB();
    scene.init(generateM0Fixture({ seed: 1, barCount: 200 }));
    const ms = Math.min(
      scene.setFormat("compact"),
      scene.setFormat("full"),
      scene.setFormat("compact"),
    );
    expect(ms).toBeLessThan(20);
  });
  it("SDF arm holds B3: p95 <= 16 ms, text <= 2 ms", () => {
    const scene = new SceneB({ arm: "sdf" });
    scene.init(generateM0Fixture({ seed: 1, barCount: 200 }));
    const r = runScenario({
      scene,
      scenario: "B3",
      durationMs: 1000,
      repetitions: 3,
      runtime: "chromium",
      runtimeVersion: "node",
      machine: captureMachineDescriptor({ gpu: "stub", driver: "stub" }),
      seed: 1,
      lodProfile: "LOD_PROFILE_M0",
      peakProcessMemMB: 1,
      peakProcessMemSource: "test",
    });
    const ext = scene.extendedStats() as unknown as Ext;
    expect(r.p95).toBeLessThanOrEqual(16);
    expect(ext.textBatchMs + ext.outlinePassMs).toBeLessThanOrEqual(2.0);
  });
  it("shedding text (L2) renders a faster frame than full text (L0): median of interleaved pairs", () => {
    const scene = new SceneB();
    scene.init(generateM0Fixture({ seed: 1, barCount: 200 }));
    let tMs = 0;
    const frameMs = (cellHeightPx: number): number => {
      scene.setCellHeight(cellHeightPx);
      tMs += 16;
      scene.step(tMs, { tMs, kind: "none" });
      return scene.stats().frameTimeMs;
    };
    // One discarded warm-up pair, then interleaved L0/L2 samples so a slow stretch hits both arms.
    frameMs(14);
    frameMs(7);
    const l0: number[] = [];
    const l2: number[] = [];
    for (let i = 0; i < LOD_PAIRS; i += 1) {
      l0.push(frameMs(14));
      l2.push(frameMs(7));
    }
    expect(median(l2)).toBeLessThan(median(l0));
  });
  it("warm atlas load (cache hit) stays within 5 ms: median of repeated loads", async () => {
    const store = new MemoryAtlasStore();
    await loadAtlas(store, "Inter", 500);
    const warm: number[] = [];
    for (let i = 0; i < WARM_LOADS; i += 1) warm.push((await loadAtlas(store, "Inter", 500)).ms);
    expect(median(warm)).toBeLessThanOrEqual(5);
  });
});
