// Wall-clock budget assertions. Run ONLY by `vitest --project perf` (no coverage): V8 coverage
// instrumentation inflates timings. The structural halves live in scene-a.test.ts (#3578).
import { describe, expect, it } from "vitest";
import { SceneA } from "../../../bench/scenes/scene-a.mjs";
import { runRepetition, runScenario } from "../../../bench/runner.mjs";
import { captureMachineDescriptor } from "../../../bench/machine.mjs";
import { generateM0Fixture } from "../../../bench/fixtures/index.mjs";
import { percentile } from "../../../bench/stats.mjs";

// Comparisons use the median of an odd number of samples after a discarded warm-up, so one stalled
// sample (GC, a preempted runner) cannot flip them: the rule scene-b.perf.test.ts uses (#3554).
// percentile() is typed `number | undefined`; NaN fails every comparison, so a missing sample can
// never pass vacuously.
const median = (xs: number[]): number => percentile(xs, 50) ?? Number.NaN;
const FRAME_PAIRS = 15;
// Odd, so the report's p95 (the median of the per-repetition p95s, §7.4) is an actual sample.
const REPETITIONS = 5;

/** p95 frame time of a B1/B2 run: one discarded warm-up repetition, then REPETITIONS measured. */
function scenarioP95(scenario: "B1" | "B2"): number {
  const scene = new SceneA();
  scene.init(generateM0Fixture({ seed: 42, barCount: 100_000 }));
  runRepetition({ scene, scenario, durationMs: 5000 });
  const report = runScenario({
    scene,
    scenario,
    durationMs: 5000,
    repetitions: REPETITIONS,
    runtime: "chromium",
    runtimeVersion: "test",
    machine: captureMachineDescriptor({ gpu: "test-stub-gpu", driver: "test-stub-driver" }),
    seed: 42,
    lodProfile: "LOD_PROFILE_M0",
    peakProcessMemMB: 0,
    peakProcessMemSource: "test",
  });
  scene.dispose();
  return report.p95;
}

describe("perf budgets: SceneA", () => {
  it("B9: cold init to first frame stays under 900ms", () => {
    const fixture = generateM0Fixture({ seed: 42, barCount: 100_000 });
    const start = performance.now();
    const scene = new SceneA();
    scene.init(fixture);
    scene.step(0, { tMs: 0, kind: "none" });
    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThanOrEqual(900);
    scene.dispose();
  });
  it("static-frame time does not scale measurably with total bar count (10k vs 100k, <=10% diff): median of interleaved frames", () => {
    const small = new SceneA();
    small.init(generateM0Fixture({ seed: 1, barCount: 10_000 }));
    const large = new SceneA();
    large.init(generateM0Fixture({ seed: 1, barCount: 100_000 }));
    let tMs = 0;
    const frameMs = (scene: SceneA): number => {
      tMs += 16;
      scene.step(tMs, { tMs, kind: "none" });
      return scene.stats().frameTimeMs;
    };
    // One discarded warm-up pair, then interleaved samples so a slow stretch hits both scenes.
    frameMs(small);
    frameMs(large);
    const t10k: number[] = [];
    const t100k: number[] = [];
    for (let i = 0; i < FRAME_PAIRS; i += 1) {
      t10k.push(frameMs(small));
      t100k.push(frameMs(large));
    }
    small.dispose();
    large.dispose();
    // Both scenes show the same *visible* window (viewport math is independent of total store
    // length), so frame cost should be near-identical regardless of the 10x difference in bars.
    const diffRatio = Math.abs(median(t100k) - median(t10k)) / Math.max(median(t10k), 1e-6);
    expect(diffRatio).toBeLessThanOrEqual(0.1);
  });
  it("B1: continuous pan holds p95 <= 12ms: median of per-repetition p95s", () => {
    expect(scenarioP95("B1")).toBeLessThanOrEqual(12);
  });
  it("B2: zoom sweep holds p95 <= 14ms: median of per-repetition p95s", () => {
    expect(scenarioP95("B2")).toBeLessThanOrEqual(14);
  });
});
