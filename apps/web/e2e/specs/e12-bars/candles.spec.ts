import { test, expect } from "@playwright/test";
import { ChartProbe } from "./chart-probe";

// E12-Q03 (#419). All cases are fixme: the chart workspace route, CMP-220/222, SCR-041/042/045/046
// do not exist in apps/web yet. Un-fixme when the blocker named on each case lands.
const BLOCKED_UI = "chart route + SCR-041 (E12-D04) + SCR-045 (#521) + SCR-046 (#523)";

test.describe("candles (US-CHART-001)", () => {
  test.fixme(true, `blocked: ${BLOCKED_UI}`);
  test("BTCUSDT 1m first/last bar in data table match GET /market/klines; forming bar updates without reload", async ({
    page,
  }) => {
    const probe = new ChartProbe(page);
    await page.goto("/chart/BTCUSDT?interval=1m");
    await expect(probe.dataRows.first()).toBeVisible();
  });
});
