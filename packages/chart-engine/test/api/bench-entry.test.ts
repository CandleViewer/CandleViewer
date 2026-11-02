// E11-T06: bench mode is reachable only through the bench build entry. `createChart` (the §8
// surface the app imports) never opens a bench chart, so its frames never reach a stage mark.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createBenchChart, STAGE_MARK_NAMES } from "../../src/api/bench.js";
import { createChart } from "../../src/api/chart.js";
import * as surface from "../../src/index.js";
import type { FrameStats, ThemeTokens } from "../../src/index.js";
import { FRAME_STATS_FIELDS, frameStatsSample } from "../../bench/engine/engine-lib.mjs";
import { asHtml, fakeContainer } from "./fake-dom.js";

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11" },
};

let marked: string[];

beforeEach(() => {
  vi.useFakeTimers();
  marked = [];
  vi.spyOn(performance, "mark").mockImplementation((name: string) => {
    marked.push(name);
    return undefined as unknown as PerformanceMark;
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the bench entry (E11-T06)", () => {
  it("opens a chart whose frames carry 06 §4.3's stage marks", () => {
    const chart = createBenchChart({ container: asHtml(fakeContainer(400, 300)), theme });
    vi.advanceTimersByTime(16);
    expect(marked).toContain("cv.frame.start");
    expect(marked).toContain("cv.stage.compositePresent");
    expect(STAGE_MARK_NAMES).toHaveLength(11);
    chart.dispose();
  });

  it("is not part of the §8 surface, and createChart's frames never mark", () => {
    // The runtime surface is main's (createChart, toTicks since E12-S06); the bench entry is not in it.
    expect(Object.keys(surface)).toContain("createChart");
    for (const k of ["createBenchChart", "STAGE_MARK_NAMES"])
      expect(Object.keys(surface)).not.toContain(k);
    const chart = createChart({ container: asHtml(fakeContainer(400, 300)), theme });
    vi.advanceTimersByTime(16);
    expect(marked).toEqual([]);
    chart.dispose();
  });
});

// E11-T06 B1: the bench page reads `frameStats` through this helper; a field FrameStats lacks
// (the old `frameTimeMs`) must fail loudly, never record NaN.
describe("the page's frameStats shape (B1 regression)", () => {
  const stats: FrameStats = {
    fps: 60,
    frameTimeMsP50: 3,
    frameTimeMsP95: 4.5,
    drawCalls: 6,
    triangles: 10,
    uploadedBytesPerSec: 0,
    lodCandles: 1,
    lodFootprint: 0,
    gpuMemoryMbEstimate: 1,
    renderProfile: "full",
  };
  it("reads only fields FrameStats really has", () => {
    for (const k of FRAME_STATS_FIELDS) expect(Object.keys(stats)).toContain(k);
    expect(frameStatsSample(stats)).toEqual({ drawCalls: 6, lod: 1, frameMs: 4.5 });
  });
  it("throws on a missing or non-finite field instead of recording NaN", () => {
    for (const k of FRAME_STATS_FIELDS) {
      const rest: Record<string, unknown> = { ...stats };
      delete rest[k];
      expect(() => frameStatsSample(rest)).toThrow(`frameStats.${k} is missing or not finite`);
      expect(() => frameStatsSample({ ...stats, [k]: NaN })).toThrow(/not finite/);
    }
    expect(() => frameStatsSample({ ...stats, frameTimeMs: 4 })).not.toThrow();
    expect(() => frameStatsSample(null)).toThrow(/drawCalls/);
  });
});
