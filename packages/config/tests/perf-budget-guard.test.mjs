// Self-tests for the guard matcher (src/perf-budget-guard.mjs). The guard itself runs per package,
// from a unit-project test in each perf-owning package (chart-engine, protocol, rule-graph).
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { GOOD_UPPER, bareBounds, scanPerfTests } from "../src/perf-budget-guard.mjs";

describe("the matcher", () => {
  it("accepts budget() of a literal or a SPEC constant, and a > 0 clock guard", () => {
    expect(bareBounds("expect(t, why(t, 8)).toBeLessThanOrEqual(budget(8));")).toEqual([]);
    expect(bareBounds("expect(t).toBeLessThan(budget(RESTORE_BUDGET_MS));")).toEqual([]);
    expect(bareBounds("expect(t).toBeGreaterThan(0);")).toEqual([]);
  });
  it("rejects a raw bound, an arithmetic wrapper, budget() as the subject and a throughput floor", () => {
    expect(bareBounds("expect(t).toBeLessThan(5);")).toHaveLength(1);
    expect(bareBounds("expect(t).toBeLessThan(budget(5) * 10);")).toHaveLength(1);
    expect(bareBounds("expect(budget(x)).toBeLessThan(5);")).toHaveLength(1);
    expect(bareBounds("expect(t).toBeLessThan(5); budget(1);")).toHaveLength(1);
    expect(bareBounds("expect(t).toBeGreaterThan(100);")).toHaveLength(1);
  });
  it("catches a bound split across lines", () => {
    expect(bareBounds("expect(t)\n  .toBeLessThan(\n    5,\n  );")).toHaveLength(1);
    expect(bareBounds("expect(t)\n  .toBeLessThan(\n    budget(5),\n  );")).toEqual([]);
  });
  it("has no overlapping whitespace runs in the upper-bound pattern (CodeQL ReDoS)", () => {
    // The old tail `\s*,?\s*\)` let two runs claim the same whitespace: polynomial backtracking.
    expect(GOOD_UPPER.source).not.toContain(String.raw`\s*,?\s*`);
    const evil = `expect(t).toBeLessThan(budget(0)${"\t".repeat(200)}x`; // within the input cap
    expect(bareBounds(evil)).toHaveLength(1);
    expect(bareBounds("expect(t).toBeLessThan(budget(8) \t , \t );")).toEqual([]);
  });
  it("honours an exemption only with an allowed reason on the line above the statement", () => {
    expect(bareBounds("// budget-exempt: ratio (two runs)\nexpect(r).toBeLessThan(2);")).toEqual(
      [],
    );
    expect(bareBounds("// budget-exempt: ratio\nexpect(r)\n  .toBeLessThan(2);")).toEqual([]);
    expect(bareBounds("// budget-exempt: because\nexpect(r).toBeLessThan(2);")).toHaveLength(1);
    expect(bareBounds("// budget-exempt:\nexpect(r).toBeLessThan(2);")).toHaveLength(1);
    expect(bareBounds("// budget-exempt: ratio\n\nexpect(r).toBeLessThan(2);")).toHaveLength(1);
  });
});

describe("scanPerfTests", () => {
  it("finds perf tests recursively and reports bare bounds with file and line", () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), "perf-guard-"));
    try {
      mkdirSync(path.join(dir, "a/node_modules"), { recursive: true });
      writeFileSync(path.join(dir, "ok.perf.test.ts"), "expect(t).toBeLessThan(budget(5));\n");
      writeFileSync(path.join(dir, "a/bad.perf.test.ts"), "\nexpect(t).toBeLessThan(5);\n");
      writeFileSync(path.join(dir, "a/node_modules/x.perf.test.ts"), "expect(t).toBeLessThan(5);");
      writeFileSync(path.join(dir, "a/plain.test.ts"), "expect(t).toBeLessThan(5);");
      const { files, offenders } = scanPerfTests(dir);
      expect(files).toEqual([path.join("a", "bad.perf.test.ts"), "ok.perf.test.ts"]);
      expect(offenders).toEqual([
        `${path.join("a", "bad.perf.test.ts")}:2: expect(t).toBeLessThan(5);`,
      ]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
