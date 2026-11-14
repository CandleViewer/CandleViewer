import { expect, test } from "@playwright/test";
import { displayDecimal, formatBarTime } from "../../../src/chart/a11y/format";
import { axeFindings, goldenBars, openChart, patient } from "./bars-harness";
import { BLOCKED, blockedBy } from "./blockers";

// E12-Q03 (#419), US-CHART-001: E12-TC-A06 (plan `qa/plans/e12-bars-and-series-test-plan.md`). The
// forming-bar case, E12-TC-A04, is held back until `sendBars` has its sender on `main` (BQ-7).
const BARS = goldenBars("btcusdt-2026-09-01", "time:1");
const ONE_MINUTE = 60_000;
const us = (t: string): number => Date.parse(t) * 1_000;

test.describe("candles (US-CHART-001)", blockedBy(BLOCKED.table), () => {
  test("BTCUSDT 1m: the data table's first and last bars match the served klines", async ({
    page,
  }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT 1m", {
      symbol: "BTCUSDT",
      bars: BARS,
    });
    await probe.openTableByKey();
    await patient(probe.dataTable).toBeVisible();
    await expect(probe.dataTable.locator(":focus")).toHaveCount(1);
    expect(await probe.barsLoaded()).toBe(BARS.length);
    for (const bar of [BARS[0], BARS.at(-1)]) {
      if (bar === undefined) throw new Error("the golden has no bars");
      const row = probe.barRow(formatBarTime(us(bar.t), ONE_MINUTE));
      await page.keyboard.press(bar === BARS[0] ? "Control+Home" : "Control+End");
      await expect(row).toContainText(displayDecimal(bar.o));
      await expect(row).toContainText(displayDecimal(bar.c));
    }
    expect(backend.refused()).toEqual([]);
    expect(await axeFindings(page)).toEqual([]);
  });

  test("Escape leaves the table and focus returns to the chart view", async ({ page }) => {
    const { probe } = await openChart(page, "BTCUSDT 1m", { symbol: "BTCUSDT", bars: BARS });
    await probe.openTableByKey();
    await patient(probe.dataTable).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(probe.dataTable).toHaveCount(0);
    await expect(probe.chartButton).toHaveAttribute("aria-pressed", "true");
  });
});
