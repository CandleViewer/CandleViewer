// Class guard for #3554 / #3578. The `unit` project runs under V8 coverage, which slows code and
// stalls timers, so an assertion on the wall clock there fails whenever a runner is loaded (C-9.3,
// C-13.7). Wall-clock budgets belong in `*.perf.test.ts` (the `perf` project, no coverage); see
// .claude/rules/31-chart-engine.md. This test makes that mechanical.
//
// It reads every test/**/*.test.ts except *.perf.test.ts (the `unit` globs of vitest.config.mjs),
// ignores comments, and fails when an `expect(` has a wall-clock source on its own line or in the
// WINDOW lines above it:
//   1. In any file: a raw clock read (performance.now, hrtime, Date.now).
//   2. In a file that builds SceneA, SceneB or SceneB5: those scenes mix performance.now() readings
//      into frameTimeMs / perStageMs / textBatchMs ..., and bench/report.mjs throws when the
//      readings drift. So (a) any call to the bench runner is forbidden outright (a count-only
//      assertion on its report still inherits that residual guard) and (b) so are the measured
//      members and p50/p95/p99 near an `expect(`. SceneC and StubScene model or seed their stage
//      costs, so tests of them are deterministic and unaffected. A new clock-fed scene must be
//      added to CLOCKED_SCENE.
//
// Nothing is allow-listed: a test that trips the rule moves its timing assertion to a perf file
// and keeps counted assertions here. A fake clock injected as an argument (instrumentation.test.ts)
// is not the global clock and passes.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const TEST_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const WINDOW = 15;
// The escaped dots and `hr[t]ime` keep this file from matching its own patterns.
const RAW_CLOCK = /\b(?:performance\s*\.\s*now|hr[t]ime|Date\s*\.\s*now)\b/;
const CLOCKED_SCENE = /\bnew Scene(?:A|B|B5)\s*\(/;
const RUNNER_CALL = /\brunScenario\s*\(/;
const MEASURED =
  /\b(?:frameTimeMs|perStageMs|textBatchMs|outlinePassMs|lastRebuildMs|timeToFirstFrameMs|p50|p95|p99)\b/;
const EXPECT_CALL = /\bexpect(?:\.soft|\.poll)?\s*\(/;

// Blanks `//` comments and block-comment lines so prose cannot trip the rule. Conservative on
// purpose: it never swallows code (a `//` inside a URL string or a `/*` inside a glob is kept).
const code = (source: string): string[] =>
  source
    .split(/\r?\n/)
    .map((line) => (/^\s*(?:\/\*|\*)/.test(line) ? "" : line.replace(/(^|\s)\/\/.*$/, "$1")));

function scan(path: string, source: string): string[] {
  const lines = code(source);
  const clocked = lines.some((line) => CLOCKED_SCENE.test(line));
  const found: string[] = [];
  lines.forEach((line, index) => {
    const at = `${path}:${index + 1}`;
    if (clocked && RUNNER_CALL.test(line)) {
      found.push(
        `${at}: clock-fed scene run through the bench runner (its residual guard reads the clock)`,
      );
    }
    if (!EXPECT_CALL.test(line)) return;
    const feeder = lines
      .slice(Math.max(0, index - WINDOW), index + 1)
      .find((above) => RAW_CLOCK.test(above) || (clocked && MEASURED.test(above)));
    if (feeder !== undefined)
      found.push(`${at}: expect( within ${WINDOW} lines of \`${feeder.trim()}\``);
  });
  return found;
}

const unitTestFiles = (): string[] =>
  readdirSync(TEST_ROOT, { encoding: "utf8", recursive: true })
    .map((entry) => entry.replaceAll("\\", "/"))
    .filter((entry) => entry.endsWith(".test.ts") && !entry.endsWith(".perf.test.ts"))
    .sort();

describe("class guard: no wall-clock assertion in the unit project (#3554, #3578)", () => {
  it("finds no unit-project test that asserts on the wall clock", () => {
    const files = unitTestFiles();
    expect(files).toContain("bench/scenes/scene-a.test.ts");
    expect(files.filter((file) => file.endsWith(".perf.test.ts"))).toEqual([]);
    const read = (file: string): string => readFileSync(join(TEST_ROOT, file), "utf8");
    expect(files.flatMap((file) => scan(file, read(file)))).toEqual([]);
  });

  // Samples are built from parts so this file never contains a clock read, a runner call or a
  // clock-fed scene itself.
  const NOW = ["performance", "now()"].join(".");
  const RUN = ["run", "Scenario"].join("");
  const CLOCKED = ["new Scene", "A()"].join("");
  const sample = (...lines: string[]): string => lines.join("\n");

  it("flags a raw clock read that feeds an assertion, in any file", () => {
    const src = sample(`const t0 = ${NOW};`, "work();", `expect(${NOW} - t0).toBeLessThan(5);`);
    expect(scan("x.test.ts", src)).toHaveLength(1);
  });

  it("passes a fake clock injected as an argument and a clock named only in a comment", () => {
    const src = sample(`// ${NOW} stalls under coverage`, "const perf = { now: () => 4 };");
    expect(scan("x.test.ts", sample(src, "expect(perf.now()).toBe(4);"))).toEqual([]);
  });

  it("forbids the runner and measured members only where a clock-fed scene is built", () => {
    const body = [`const report = ${RUN}({ scene });`, "expect(report.p95).toBeLessThan(12);"];
    const clocked = sample(`const scene = ${CLOCKED};`, ...body);
    const seeded = sample("const scene = new StubScene();", ...body);
    expect(scan("x.test.ts", clocked)).toHaveLength(2);
    expect(scan("x.test.ts", seeded)).toEqual([]);
  });
});
