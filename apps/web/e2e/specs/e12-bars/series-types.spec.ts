import { test, expect } from "@playwright/test";
import { ChartProbe } from "./chart-probe";

// E12-Q03 (#419). All cases are fixme: the chart workspace route, CMP-220/222, SCR-041/042/045/046
// do not exist in apps/web yet. Un-fixme when the blocker named on each case lands.
const BLOCKED_UI = "CMP-222 ChartTypeToggle (#244) + series types (#533) + SCR-045 (#521)";

test.describe("series types (US-CHART-002)", () => {
  test.fixme(true, `blocked: ${BLOCKED_UI}`);
  test("candle -> OHLC -> line -> area -> Heikin-Ashi -> baseline issues no kline/bar refetch and keeps bar count", async ({
    page,
  }) => {
    const probe = new ChartProbe(page);
    await page.goto("/chart/BTCUSDT?interval=5m");
    await expect(probe.dataRows.first()).toBeVisible();
    const before = await probe.dataRows.count();
    const requests = probe.trackMarketRequests();
    for (const type of ["OHLC bar", "Line", "Area", "Heikin-Ashi", "Baseline"]) {
      await page.getByRole("radio", { name: type }).click();
      await expect(probe.dataRows).toHaveCount(before);
    }
    expect(requests).toEqual([]);
  });
  test("volume sub-pane mounts as a linked pane sharing the time axis", async () => {});
});
