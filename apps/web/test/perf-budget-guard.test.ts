// Guard: every wall-clock bound in this package's `*.perf.test.ts` goes through `budget(<spec>)`
// (runner calibration, packages/config/src/perf-budget-guard.mjs). It lives in the unit project so
// editing a perf file re-runs it (the perf project is not part of the unit task).
import path from "node:path";
import { describe, expect, it } from "vitest";
import { scanPerfTests } from "@candleviewer/config/perf-budget-guard";

describe("perf budgets go through the runner calibration", () => {
  it("every bound in this package's perf tests uses budget(<spec>)", () => {
    const { files, offenders } = scanPerfTests(path.resolve(import.meta.dirname));
    expect(files.length).toBeGreaterThan(0);
    expect(offenders).toEqual([]);
  });
});
