// E11-T06: the real-engine scenario registry, its 26 §13 gates and the pure arithmetic the bench
// page, the runner and ci-compare share.
import { describe, expect, it } from "vitest";
import {
  ENGINE_CHROMIUM_FLAGS,
  ENGINE_REPS,
  ENGINE_SCENARIO_IDS,
  ENGINE_SCENARIOS,
  ENGINE_STAGES,
  FRAME_START,
  PARTIAL_CONTENT,
  PER_PR_SCENARIOS,
  STAGE_PREFIX,
  STUB_SCENARIOS,
  framesFromMarks,
  gateRows,
  growthPct,
  heapReadingMb,
  lodChanges,
  memoryDeltaMb,
  panWindow,
  spreadPct,
  stubCell,
  summariseEngineCell,
  zoomSpacing,
} from "../../../bench/engine/engine-lib.mjs";
import { FRAME_STAGES } from "../../../src/scene/frame-scheduler.js";
import { STAGE_MARK_NAMES } from "../../../src/scene/stage-marks.js";

type Obj = Record<string, unknown>;

describe("the scenario registry (26 §13)", () => {
  it("lists B1 to B10; B1, B2, B5, B6, B9 per PR; B10 nightly only; C-9.1's five reps", () => {
    expect(ENGINE_SCENARIO_IDS).toEqual([
      "B1",
      "B2",
      "B3",
      "B4",
      "B5",
      "B6",
      "B7",
      "B8",
      "B9",
      "B10",
    ]);
    expect(PER_PR_SCENARIOS).toEqual(["B1", "B2", "B5", "B6", "B9"]);
    expect(ENGINE_SCENARIOS.B10.nightly).toBe(true);
    expect(ENGINE_REPS).toBe(5);
  });

  it("records B3, B4, B7 and B8 as stubs, explicitly, naming the owner Epic", () => {
    expect(STUB_SCENARIOS).toEqual(["B3", "B4", "B7", "B8"]);
    expect(STUB_SCENARIOS.map((id: string) => stubCell(id))).toEqual([
      expect.objectContaining({ scenario: "B3", status: "stub", owner: "E18" }),
      expect.objectContaining({ scenario: "B4", status: "stub", owner: "E21" }),
      expect.objectContaining({ scenario: "B7", status: "stub", owner: "E17" }),
      expect.objectContaining({ scenario: "B8", status: "stub", owner: "E14" }),
    ]);
    expect(stubCell("B3").reason).toMatch(/^not implemented: /);
  });

  it("carries 26 §13's primary and secondary gate figures", () => {
    const max = (id: string) =>
      (
        (ENGINE_SCENARIOS as unknown as Record<string, { gates?: { max: number }[] }>)[id]?.gates ??
        []
      ).map((g) => g.max);
    expect(max("B1")).toEqual([12, 8]);
    expect(max("B2")).toEqual([14, 6]);
    expect(max("B5")).toEqual([16.7, 40]);
    expect(max("B6")).toEqual([16.7, 70]);
    expect(max("B9")).toEqual([900, 5]);
    expect(max("B10")).toEqual([600, 5]);
  });

  it("uses the engine's own stage and mark names", () => {
    expect(ENGINE_STAGES).toEqual([...FRAME_STAGES]);
    expect(STAGE_MARK_NAMES.slice(0, 9)).toEqual(
      ENGINE_STAGES.map((s: string) => STAGE_PREFIX + s),
    );
    expect(STAGE_MARK_NAMES).toContain(FRAME_START);
  });
});

describe("framesFromMarks", () => {
  const frame = (t0: number): { name: string; startTime: number }[] => [
    { name: FRAME_START, startTime: t0 },
    { name: "cv.stage.inputHandling", startTime: t0 + 1 },
    { name: "cv.stage.dataWindowRecompute", startTime: t0 + 1.5 },
    { name: "cv.stage.layout", startTime: t0 + 2 },
    { name: "cv.stage.candleGeometry", startTime: t0 + 4 },
    { name: "cv.stage.footprintTextGeometry", startTime: t0 + 4 },
    { name: "cv.stage.heatmapUpload", startTime: t0 + 4 },
    { name: "cv.stage.paneRedraw", startTime: t0 + 5 },
    { name: "cv.stage.overlayRedraw", startTime: t0 + 5 },
    { name: "cv.stage.domMirrorSync", startTime: t0 + 5 },
    { name: "cv.stage.compositePresent", startTime: t0 + 8 },
  ];

  it("splits frames at the start mark and attributes each boundary's time to its stage", () => {
    const out = framesFromMarks([{ name: "other", startTime: 0 }, ...frame(10), ...frame(30)]);
    expect(out.frameMs).toEqual([8, 8]);
    expect(out.stageMs["inputHandling"]).toEqual([1, 1]);
    expect(out.stageMs["candleGeometry"]).toEqual([2, 2]); // from the layout's end
    expect(out.stageMs["compositePresent"]).toEqual([3, 3]);
    expect(out.stageMs["heatmapUpload"]).toEqual([0, 0]);
  });

  it("drops a frame that never closed and marks before any frame", () => {
    const partial = frame(0).slice(0, 5);
    expect(framesFromMarks([...frame(100).slice(3), ...partial]).frameMs).toEqual([]);
  });
});

describe("spread, growth, LOD changes", () => {
  it("publishes the spread as max minus min over the median", () => {
    expect(spreadPct([10, 10.2, 9.9, 10.1, 10])).toBeCloseTo(3, 6);
    expect(spreadPct([0, 0])).toBeNull();
  });
  it("measures soak growth as the last tenth over the first", () => {
    expect(growthPct(Array.from({ length: 20 }, (_, i) => 100 + i))).toBeCloseTo(1800 / 100.5, 6);
    expect(growthPct([1])).toBeNull();
    expect(growthPct([0, 0, 5])).toBeNull();
  });
  it("counts LOD level changes", () => {
    expect(lodChanges([0, 0, 1, 1, 2, 1])).toBe(3);
    expect(lodChanges([])).toBe(0);
  });
});

const rep = (frameMs: number[], over: Obj = {}): Obj => ({
  frameMs,
  stageMs: { candleGeometry: frameMs.map((v) => v / 2), inputHandling: frameMs.map(() => 0.1) },
  drawCalls: [3, 4, 4],
  lod: [0, 0, 1],
  memoryMb: 50,
  memoryPrecision: "precise",
  ...over,
});

describe("summariseEngineCell", () => {
  it("gates on the median of the per-rep p95s and keeps them, their spread and the worst stage", () => {
    const reps = [10, 11, 12, 13, 14].map((v) => rep([v, v, v]));
    const c = summariseEngineCell({ scenario: "B1", reps });
    expect(c).toMatchObject({ status: "ok", repetitions: 5, admissibleForAdrEvidence: true });
    expect(c.p95).toBe(12);
    expect(c.p95PerRep).toEqual([10, 11, 12, 13, 14]);
    expect(c.spreadPct).toBeCloseTo((4 / 12) * 100, 6);
    expect(c.drawCalls).toBe(4);
    expect(c.lodChanges).toBe(1);
    expect(c.memoryMb).toBe(50);
    expect(c.worstStage).toBe("candleGeometry");
    expect(c.peakMemoryMb).toBeNull();
  });
  it("summarises B9's cold init, B6's worker CPU and B10's soak", () => {
    const b9 = summariseEngineCell({ scenario: "B9", reps: [rep([], { coldInitMs: 300 })] });
    expect(b9.coldInitToFirstFrameMs).toBe(300);
    expect(b9.atlasFromCacheMs).toBeNull();
    const b6 = summariseEngineCell({ scenario: "B6", reps: [rep([5], { workerCpuPct: 40 })] });
    expect(b6.workerCpuPct).toBe(40);
    const series = Array.from({ length: 20 }, () => 200);
    const b10 = summariseEngineCell({
      scenario: "B10",
      reps: [rep([5], { memorySeriesMb: series })],
    });
    expect(b10).toMatchObject({ admissibleForAdrEvidence: true, peakMemoryMb: 200, growthPct: 0 });
  });
  it("makes a non-B9 cell with a frameless rep not-runnable, never a p95 of 0", () => {
    const reps = [rep([5, 6]), rep([])];
    const c = summariseEngineCell({ scenario: "B1", reps });
    expect(c.status).toBe("not-runnable");
    expect(c.reason).toMatch(/rep 2 .*no frame/);
    expect(c.p95).toBeUndefined();
    expect(gateRows(c)).toEqual([]);
    expect(summariseEngineCell({ scenario: "B6", reps: [rep([])] }).status).toBe("not-runnable");
    expect(summariseEngineCell({ scenario: "B1", reps: [] }).status).toBe("not-runnable");
  });
  it("names the heap figure's limit: typed-array backing stores are not counted", () => {
    const c = summariseEngineCell({ scenario: "B1", reps: [rep([5])] });
    expect(c.memoryLimit).toMatch(/ArrayBuffer backing stores .*external memory.*not counted/);
  });
  it("records an imprecise heap as such, with no figure to compare (M3)", () => {
    const reps = [rep([5]), rep([5], { memoryPrecision: "imprecise", memorySeriesMb: [9] })];
    const c = summariseEngineCell({ scenario: "B10", reps });
    expect(c).toMatchObject({ memoryPrecision: "imprecise", memoryMb: null, peakMemoryMb: null });
    expect(c.growthPct).toBeNull();
    const scope = "main thread only; the render worker's heap is not counted";
    const b6 = summariseEngineCell({ scenario: "B6", reps: [rep([5], { memoryScope: scope })] });
    expect(b6).toMatchObject({ memoryPrecision: "precise", memoryMb: 50, memoryScope: scope });
  });
  it("marks B5 and B6 partial, naming what is missing (M2)", () => {
    for (const id of ["B5", "B6"] as const) {
      expect(ENGINE_SCENARIOS[id].partial).toBe(PARTIAL_CONTENT);
      expect(summariseEngineCell({ scenario: id, reps: [rep([5])] }).partial).toBe(PARTIAL_CONTENT);
    }
    expect(PARTIAL_CONTENT).toMatch(/^partial: .*E18.*E21.*E12.*candles only$/);
    expect(summariseEngineCell({ scenario: "B1", reps: [rep([5])] }).partial).toBeUndefined();
    expect(gateRows({ scenario: "B5", status: "ok", p95: 1 })[0].metric).toMatch(/\[partial\]$/);
  });
  it("passes a page-side failure through as not-runnable", () => {
    expect(summariseEngineCell({ scenario: "B5", notRunnable: "boom" })).toEqual({
      scenario: "B5",
      status: "not-runnable",
      reason: "boom",
    });
  });
});

describe("the memory reading (M3)", () => {
  it("reads the heap only when precise memory is on", () => {
    const memory = { usedJSHeapSize: 2 * 1048576 };
    expect(heapReadingMb(memory, true)).toBe(2);
    expect(heapReadingMb(memory, false)).toBeNull();
    expect(heapReadingMb(undefined, true)).toBeNull();
    expect(heapReadingMb({ usedJSHeapSize: NaN }, true)).toBeNull();
  });
  it("records the peak above the pre-mount reading, so the fixture is excluded", () => {
    expect(memoryDeltaMb(100, [101, null, 130, 120])).toBe(30);
    expect(memoryDeltaMb(100, [90])).toBe(0);
    expect(memoryDeltaMb(null, [130])).toBeNull();
    expect(memoryDeltaMb(100, [null])).toBeNull();
  });
  it("adds --enable-precise-memory-info for the engine page", () => {
    expect(ENGINE_CHROMIUM_FLAGS).toEqual(["--enable-precise-memory-info"]);
  });
});

describe("gateRows", () => {
  it("judges each 26 §13 gate: within, over, or not measured", () => {
    const rows = gateRows({ scenario: "B1", status: "ok", p95: 12, drawCalls: 9 });
    expect(rows.map((r: Obj) => r["status"])).toEqual(["within gate", "over gate"]);
    expect(rows[0].metric).toBe("B1 frame p95 <= 12 ms (26 §13)");
    const b9 = gateRows({ scenario: "B9", status: "ok", coldInitToFirstFrameMs: 400 });
    expect(b9.map((r: Obj) => r["status"])).toEqual(["within gate", "not measured"]);
    expect(gateRows({ scenario: "B3", status: "stub" })).toEqual([]);
    expect(gateRows(null)).toEqual([]);
  });
});

describe("the scripted input", () => {
  it("pans left at 1000 px/s from the newest bar and wraps at the oldest", () => {
    const o = { bars: 1000, widthPx: 600, spacingPx: 6 };
    expect(panWindow(0, o)).toEqual({ from: 900, to: 1000 });
    expect(panWindow(600, o)).toEqual({ from: 800, to: 900 });
    expect(panWindow(5400, o).to).toBe(1000); // 900 bars shifted: back to the newest
  });
  it("sweeps the bar spacing geometrically from 0.1 to 50 px/bar", () => {
    expect(zoomSpacing(0, 20_000)).toBeCloseTo(0.1, 9);
    expect(zoomSpacing(20_000, 20_000)).toBeCloseTo(50, 9);
    expect(zoomSpacing(10_000, 20_000)).toBeCloseTo(Math.sqrt(0.1 * 50), 9);
    expect(zoomSpacing(-5, 10)).toBeCloseTo(0.1, 9);
  });
});
