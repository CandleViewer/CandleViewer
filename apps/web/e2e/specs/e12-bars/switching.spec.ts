import { expect, test } from "@playwright/test";
import { axeFindings, goldenBars, openChart, patient } from "./bars-harness";
import { BLOCKED, blockedBy } from "./blockers";
import { ChartProbe } from "./chart-probe";

// E12-Q03 (#419), US-CHART-005: E12-TC-E04 and the timeframe switch. The visible-window centre check
// (E12-TC-E01) is held back until the E11-T07 #523 head emits `visibleRange` (the BQ-8 ruling); the
// timeframe case asserts the populated panel and the 5m bar count only.
const BTC_1M = goldenBars("btcusdt-2026-09-01", "time:1");
const BTC_5M = goldenBars("btcusdt-2026-09-01", "time:5");

test.describe("symbol switch (US-CHART-005)", blockedBy(BLOCKED.probe), () => {
  test("BTCUSDT to ETHUSDT from SCR-041 keeps the GL context and never shows an empty grid", async ({
    page,
  }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT 1m", {
      symbol: "BTCUSDT",
      bars: BTC_1M,
    });
    const { glContextId } = await probe.diagnostics();
    // The same synthetic tape under the second symbol: the plumbing is asserted, not the prices.
    backend.serve({ symbol: "ETHUSDT", bars: BTC_1M });
    await page.keyboard.press("Control+K");
    await patient(probe.quickSwitcher).toBeVisible();
    await page.keyboard.type("ETHUSDT");
    await page.keyboard.press("Enter");
    await patient(new ChartProbe(page, "ETHUSDT 1m").panel).toBeVisible();
    await expect(page.getByRole("status", { name: /loading/iu })).toHaveCount(0);
    expect((await probe.diagnostics()).glContextId).toBe(glContextId);
    expect(await axeFindings(page)).toEqual([]);
  });
});

test.describe("timeframe switch (US-CHART-005)", blockedBy(BLOCKED.barModes), () => {
  test("the 5m hotkey keeps the panel populated and loads 5m bars", async ({ page }) => {
    const { probe, backend } = await openChart(page, "BTCUSDT 1m", {
      symbol: "BTCUSDT",
      bars: BTC_1M,
    });
    backend.serve({ symbol: "BTCUSDT", bars: BTC_5M });
    await probe.panel.focus();
    await page.keyboard.press("5");
    await patient(new ChartProbe(page, "BTCUSDT 5m").panel).toBeVisible();
    expect(backend.marketReads.at(-1)).toContain("interval=5");
    const fiveMinute = new ChartProbe(page, "BTCUSDT 5m");
    await fiveMinute.openTableByKey();
    expect(await fiveMinute.barsLoaded()).toBe(BTC_5M.length);
  });
});
