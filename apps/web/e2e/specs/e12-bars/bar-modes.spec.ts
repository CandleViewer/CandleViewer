import { test, expect } from "@playwright/test";
import { ChartProbe } from "./chart-probe";

// E12-Q03 (#419). All cases are fixme: the chart workspace route, CMP-220/222, SCR-041/042/045/046
// do not exist in apps/web yet. Un-fixme when the blocker named on each case lands.
const BLOCKED_UI = "SCR-042 (E12-D03 #201) + CMP-220 (#244) + SCR-045 (#521)";

test.describe("tick and volume bar modes (US-CHART-003)", () => {
  test.fixme(true, `blocked: ${BLOCKED_UI}`);
  test("tick:1000 on ETHUSDT before recording_started_at shows the partial-history marker and labelled empty region", async ({
    page,
  }) => {
    const probe = new ChartProbe(page);
    await page.goto("/chart/ETHUSDT?mode=tick:1000");
    await expect(page.getByText(/recording started/i)).toBeVisible();
    await expect(probe.dataRows.first()).toBeVisible();
  });
});
