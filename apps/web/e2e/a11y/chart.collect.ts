import { mkdirSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { HarnessReport } from "./chart-harness/main";
import { CHART_SURFACES, CHART_TOGGLES } from "./chart-harness/surfaces";
import { openScreen, STEP_TIMEOUT_MS } from "./open";
import { CHART_SCREENS, REPORT_DIR } from "./screens";

/** The record for a mirror check the engine on this tree cannot answer (plan §0, §4). */
const NOT_ASSESSED = "not assessed: surrogate not on main (pending #5480)";

// E11-Q05 (#517) collector: what each chart harness state mounted -> reports/a11y/chart-harness.json.
// axe and the tree collectors audit the same states; this one records whether the E11-S13 DOM
// mirror was engaged (runtime feature detection) and, when it was, the roles and names the
// plan's IMG-IN-APP / R-T6 rows read. Like every collector it fails only when it cannot collect (no
// chart canvas mounted); judging the content is the audit's (PR-2), never this file's.
test("collect chart harness", async ({ page }) => {
  const states: Record<string, unknown> = {};
  for (const s of CHART_SCREENS) {
    await openScreen(page, s);
    await expect(page.locator("[data-cv-chart-canvas]"), `${s.id}: no chart canvas`).toHaveCount(
      1,
      { timeout: STEP_TIMEOUT_MS },
    );
    const report = await page.evaluate(
      () => (window as unknown as { __cvChartHarness?: HarnessReport }).__cvChartHarness ?? null,
    );
    if (report === null) throw new Error(`${s.id}: the harness did not publish its report`);
    // Recorded in every state: the mirror-off state is BQ-10's evidence of the default tree.
    const dom = await page.evaluate(() => {
      const attrs = (sel: string, names: readonly string[]) => {
        const el = document.querySelector(sel);
        return el && Object.fromEntries(names.map((n) => [n, el.getAttribute(n)]));
      };
      return {
        root: attrs("[data-cv-chart-root]", ["role", "aria-roledescription", "aria-label"]),
        canvas: attrs("[data-cv-chart-canvas]", ["role", "aria-label", "aria-hidden", "tabindex"]),
        mirrorTables: document.querySelectorAll("[data-cv-dom-mirror] table").length,
      };
    });
    const mirror =
      report.mirrorRequested && !report.mirrorEngaged ? NOT_ASSESSED : "recorded (heuristic)";
    states[s.id] = { ...report, mirror, dom };
  }
  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(
    `${REPORT_DIR}/chart-harness.json`,
    JSON.stringify({ surfaces: CHART_SURFACES, toggles: CHART_TOGGLES, states }, null, 2),
  );
});
