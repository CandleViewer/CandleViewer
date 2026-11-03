import { describe, expect, it } from "vitest";
import { foldSets, median, setLine, toMarkdown } from "../../scripts/perf-sets.mjs";
import type { ShellPerfReport } from "../../e2e/perf/support/report";

// E10-Q04 PR-4: the CI fold of three cold-start sets (BQ-Q04-03 with the critic's correction).
function report(totals: readonly number[], cpu = 20): ShellPerfReport {
  const sorted = [...totals].sort((a, b) => a - b);
  const stage = { stage: "shell_cold_start_ms", n: totals.length, p50: sorted[4], p95: sorted[9] };
  return {
    stages: [stage],
    runs: totals.map((t) => ({ shell_cold_start_ms: t })),
    calibration: { cpu },
  } as unknown as ShellPerfReport;
}
const ten = (base: number) => Array.from({ length: 10 }, (_, i) => base + i * 10);

describe("perf-sets: three cold-start sets in one recorded line", () => {
  it("takes the median of the p95s and, as the trend, the median of the p50s", () => {
    const line = foldSets(
      "electron",
      [report(ten(1000)), report(ten(1200)), report(ten(900))],
      null,
    );
    expect(line.sets.map((s) => s.p50)).toEqual([1040, 1240, 940]);
    expect([line.medianP95Ms, line.trendP50Ms]).toEqual([1090, 1040]);
    expect([line.baselineP50Ms, line.flagged]).toEqual([null, false]);
  });

  it("records each set's spread (max / min) and calibration", () => {
    expect(setLine(report([100, 200, 150], 26))).toMatchObject({ spread: 2, calibrationCpu: 26 });
  });

  it("flags a trend 15 % or more above the baseline, and not one below it", () => {
    const sets = [report(ten(1150)), report(ten(1150)), report(ten(1150))];
    expect(foldSets("browser", sets, { trendP50Ms: 1000 }).flagged).toBe(true); // 1190: +19 %
    expect(foldSets("browser", sets, { trendP50Ms: 1100 }).flagged).toBe(false); // +8 %
  });

  it("refuses fewer than three sets and a report without the total stage", () => {
    expect(() => foldSets("electron", [report(ten(1)), report(ten(1))], null)).toThrow(/3/u);
    const empty = { stages: [], runs: [], calibration: { cpu: 1 } } as unknown as ShellPerfReport;
    expect(() => setLine(empty)).toThrow(/shell_cold_start_ms/u);
  });

  it("writes the summary with no budget comparison and says when no baseline exists", () => {
    const md = toMarkdown(
      foldSets("electron", [report(ten(1)), report(ten(1)), report(ten(1))], null),
    );
    expect(md).toContain("no baseline yet");
    expect(md).toContain("never compared with the budget");
    expect(median([3, 1, 2])).toBe(2);
  });
});
