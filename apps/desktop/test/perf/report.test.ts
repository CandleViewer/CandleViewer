import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  BUDGET_MS,
  SINCE_READY,
  budgetLine,
  buildReport,
  nearestRank,
  slowestStage,
  summarize,
  toMarkdown,
  writeReport,
  type RunSample,
} from "../../e2e/perf/support/report";

// E10-Q04 PR-2: the cold-start report maths (nearest rank, the verdict rule, the slowest stage)
// on fixed samples; no launch, no clock.

/** Ten runs: whenReady at 100 + i, bootstrap at 400 + 10i, interactive at `total(i)`. */
const runs = (total: (i: number) => number): RunSample[] =>
  Array.from({ length: 10 }, (_, i) => ({
    whenReady: 100 + i,
    shell_bootstrap_ms: 400 + 10 * i,
    shell_cold_start_ms: total(i),
  }));

describe("nearestRank", () => {
  it("nearestRank_n10_p95IsTheMaximumAndP50TheFifth", () => {
    const values = [9, 1, 8, 2, 7, 3, 6, 4, 5, 10];
    expect(nearestRank(values, 95)).toBe(10);
    expect(nearestRank(values, 50)).toBe(5);
  });

  it("nearestRank_noSamples_throws", () => {
    expect(() => nearestRank([], 50)).toThrow(/no samples/u);
  });
});

describe("summarize and slowestStage", () => {
  it("summarize_runs_givesP50P95PerStageInFirstSeenOrder", () => {
    const stats = summarize(runs((i) => 1_000 + i));
    expect(stats.map((s) => s.stage)).toEqual([
      "whenReady",
      "shell_bootstrap_ms",
      "shell_cold_start_ms",
    ]);
    expect(stats[2]).toEqual({ stage: "shell_cold_start_ms", n: 10, p50: 1_004, p95: 1_009 });
  });

  it("slowestStage_largestMedianSegment_isNamed", () => {
    // Segments: whenReady ~100, bootstrap ~300, interactive 2 000: interactive is slowest.
    expect(slowestStage(runs((i) => 2_400 + 10 * i))).toBe("shell_cold_start_ms");
    // Interactive right after bootstrap: bootstrap's ~300 ms segment is the slowest.
    expect(slowestStage(runs((i) => 401 + 10 * i))).toBe("shell_bootstrap_ms");
  });
});

describe("budgetLine", () => {
  const over = runs((i) => 3_000 + i); // p95 3 009 > 3 000
  const under = runs((i) => 2_000 + i);

  it("budgetLine_referenceOverBudget_failsAndNamesTheSlowestStage", () => {
    expect(budgetLine("electron", over, "reference")).toEqual({
      stage: "shell_cold_start_ms",
      limitMs: 3_000,
      p95Ms: 3_009,
      verdict: "FAIL",
      slowestStage: "shell_cold_start_ms",
    });
  });

  it("budgetLine_ciOverBudget_isRecordedNeverFailed", () => {
    expect(budgetLine("electron", over, "ci").verdict).toBe("RECORDED");
    expect(budgetLine("electron", under, "ci").verdict).toBe("RECORDED");
  });

  it("budgetLine_belowClass_metPassesMissedIsInconclusive", () => {
    expect(budgetLine("electron", under, "below-class").verdict).toBe("PASS");
    expect(budgetLine("electron", over, "below-class").verdict).toBe("INCONCLUSIVE");
  });

  it("budgetLine_browser_readsTheFourSecondBudget", () => {
    expect(budgetLine("browser", over, "reference")).toMatchObject({
      limitMs: 4_000,
      verdict: "PASS",
    });
  });

  it("budgetLine_aRunWithoutTheTotal_isNeverAPass", () => {
    const missing = [...under.slice(1), { whenReady: 100 }];
    expect(budgetLine("electron", missing, "reference")).toMatchObject({
      p95Ms: null,
      verdict: "FAIL",
    });
  });
});

describe("buildReport and its writers", () => {
  const dirs: string[] = [];
  afterEach(() => {
    for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
  });

  const input = {
    target: "electron" as const,
    host: "ci" as const,
    calibration: { cpu: 54, cpuSpread: 1.2, resampled: false },
    versions: { electron: "45.0.0" },
    runs: runs((i) => 2_500 + i),
    unanswered: ["GET /api/v1/onboarding/checklist"],
  };

  it("buildReport_slowCalibration_neverWidensTheBudget", () => {
    const report = buildReport(input); // cpu 3x the reference
    expect(report.budget.limitMs).toBe(BUDGET_MS.electron);
    expect(report.calibration).toEqual(input.calibration);
    expect(report.schema).toBe("cv-shell-perf-report/1");
  });

  it("buildReport_electronRuns_addsWhenReadyToInteractive", () => {
    const row = buildReport(input).stages.find((s) => s.stage === SINCE_READY);
    expect(row).toEqual({ stage: SINCE_READY, n: 10, p50: 2_400, p95: 2_400 });
  });

  it("toMarkdown_ciReport_tablesEveryStageAndSaysInformational", () => {
    const md = toMarkdown(buildReport(input));
    expect(md).toContain("| shell_cold_start_ms | 10 | 2504.0 | 2509.0 |");
    expect(md).toContain("**RECORDED** (informational on CI)");
    expect(md).toContain("Unanswered stub requests: GET /api/v1/onboarding/checklist");
  });

  it("writeReport_dir_writesJsonAndMarkdown", () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), "cv-report-test-"));
    dirs.push(dir);
    const [json, md] = writeReport(dir, buildReport(input));
    expect(JSON.parse(readFileSync(json, "utf8"))).toMatchObject({
      target: "electron",
      host: "ci",
    });
    expect(readFileSync(md, "utf8")).toContain("## Shell cold start (electron), n = 10, host ci");
  });
});
