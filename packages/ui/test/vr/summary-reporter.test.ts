import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { FullConfig } from "playwright/test";
import { describe, expect, it } from "vitest";
import SummaryReporter from "../../vr/summary-reporter.js";

const story = (id: string, tags: string[] = []) => ({ id, type: "story", tags });

/** An index of 2 stories (12 cells) and a perf story, written where a built Storybook would be. */
function builtIndex(): string {
  const dir = mkdtempSync(join(tmpdir(), "vr-summary-"));
  const entries = [story("a-b--one"), story("a-b--two"), story("a-b--perf", ["perf"])];
  writeFileSync(
    join(dir, "index.json"),
    JSON.stringify({ entries: Object.fromEntries(entries.map((e) => [e.id, e])) }),
  );
  return join(dir, "index.json");
}

// The reporter reads these fields only; its own parameter types say which.
type Suite = Parameters<SummaryReporter["onBegin"]>[1];
type Case = Parameters<SummaryReporter["onTestEnd"]>[0];
type Result = Parameters<SummaryReporter["onTestEnd"]>[1];
const config = (shard: FullConfig["shard"]) => ({ shard }) as FullConfig;
const suite = (count: number): Suite => ({ allTests: () => Array.from({ length: count }) });
const test = (title: string): Case => ({ title });
/** A failed toHaveScreenshot, as Playwright words it. */
const MISMATCH = "expect(page).toHaveScreenshot(expected) failed\n\n  41 pixels are different.";
const MISSING =
  "A snapshot doesn't exist at /repo/packages/ui/vr/baselines/a-b--one--dark--compact.png.";
const result = (
  status: Result["status"],
  extra: { ownGlobals?: boolean; notCaptured?: string; error?: string; fonts?: string } = {},
): Result => ({
  status,
  annotations: [
    ...(extra.ownGlobals ? [{ type: "own-globals", description: "renders theme=light" }] : []),
    ...(extra.notCaptured === undefined
      ? []
      : [{ type: "not-captured", description: extra.notCaptured }]),
    ...(extra.fonts === undefined ? [] : [{ type: "fonts", description: extra.fonts }]),
  ],
  ...(extra.error === undefined ? {} : { error: { message: extra.error } }),
});

function run(
  shard: FullConfig["shard"],
  results: [string, Result][],
  env: Readonly<Record<string, string | undefined>> = {},
): string[] {
  const lines: string[] = [];
  const write = (line: string): number => lines.push(line);
  const reporter = new SummaryReporter({ index: builtIndex(), write, env });
  reporter.onBegin(config(shard), suite(results.length));
  for (const [title, outcome] of results) reporter.onTestEnd(test(title), outcome);
  reporter.onEnd();
  return lines;
}

const DIFFS = "a missing baseline, or more pixels changed than 2% of the capture, at most 25";

describe("the VR job summary", () => {
  it("logs the matrix's cell count, the stories left out, this run's share and a zero diff count", () => {
    const lines = run({ current: 2, total: 4 }, [
      ["a-b--one--dark--compact", result("passed", { ownGlobals: true })],
      ["a-b--one--light--compact", result("passed")],
    ]);
    expect(lines).toEqual([
      "- VR matrix: 12 cells (2 stories x 3 themes x 2 densities); stories left out: " +
        "a-b--perf (perf: a wall-clock benchmark, which the storybook gate skips too)",
      "- This run: 2 tests (shard 2 of 4); cells showing a theme or density their story sets itself: 1",
      `- VR diffs: 0 (${DIFFS})`,
    ]);
  });

  it("names the shard the vr job's VR_SHARD selected", () => {
    const lines = run(null, [["a-b--one--dark--compact", result("passed")]], { VR_SHARD: "3/10" });
    expect(lines[1]).toBe(
      "- This run: 1 tests (shard 3 of 10); cells showing a theme or density their story sets itself: 0",
    );
  });

  it("names the faces Chromium drew for the token families", () => {
    const fonts =
      "font.family.ui Inter (Inter-Regular); font.family.mono JetBrains Mono (JetBrainsMono-Regular)";
    const lines = run(null, [
      ["Chromium draws the token families in their own faces", result("passed", { fonts })],
    ]);
    expect(lines).toContain(`- Fonts drawn: ${fonts}`);
  });

  it("counts as diffs only a mismatched or missing screenshot; a timeout or other error goes apart", () => {
    const lines = run(null, [
      ["a-b--one--dark--compact", result("failed", { error: MISMATCH })],
      ["a-b--one--light--compact", result("failed", { error: MISSING })],
      [
        "a-b--two--high-contrast--comfortable",
        result("timedOut", { error: "Test timeout of 30000ms exceeded." }),
      ],
      [
        "a-b--two--light--compact",
        result("failed", { error: "TypeError: page.evaluate failed\n  at x" }),
      ],
      ["every cell has a baseline and every baseline a cell", result("failed")],
      ["a-b--two--dark--compact", result("passed")],
    ]);
    expect(lines.slice(1)).toEqual([
      "- This run: 6 tests; cells showing a theme or density their story sets itself: 0",
      `- VR diffs: 2 (${DIFFS}): a-b--one--dark--compact, a-b--one--light--compact`,
      "- Cells that failed otherwise: 2 (a timeout or an error outside the comparison): " +
        "a-b--two--high-contrast--comfortable (Test timeout of 30000ms exceeded.), " +
        "a-b--two--light--compact (TypeError: page.evaluate failed)",
      "- Other failures: every cell has a baseline and every baseline a cell",
    ]);
  });

  it("names the cells it could not capture apart from the diffs, each with its reason", () => {
    const play =
      "play function failed: AssertionError: expected focus\n  at play (Menu.stories.tsx:9)";
    const lines = run(null, [
      ["a-b--one--dark--compact", result("failed", { notCaptured: play, error: play })],
      [
        "a-b--one--light--compact",
        result("failed", {
          notCaptured: "did not settle: the DOM was still changing after 3000 ms",
        }),
      ],
      ["a-b--two--dark--compact", result("failed", { error: MISMATCH })],
    ]);
    expect(lines.slice(2)).toEqual([
      `- VR diffs: 1 (${DIFFS}): a-b--two--dark--compact`,
      "- Cells not captured: 2 (a play function failed, Storybook errored, or the page never held " +
        "still): a-b--one--dark--compact (play function failed: AssertionError: expected focus), " +
        "a-b--one--light--compact (did not settle: the DOM was still changing after 3000 ms)",
    ]);
  });
});
