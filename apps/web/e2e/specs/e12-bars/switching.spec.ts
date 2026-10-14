import { test, expect } from "@playwright/test";
import { ChartProbe } from "./chart-probe";

// E12-Q03 (#419). All cases are fixme: the chart workspace route, CMP-220/222, SCR-041/042/045/046
// do not exist in apps/web yet. Un-fixme when the blocker named on each case lands.
const BLOCKED_UI = "SCR-041 (#240), SCR-046 GL context id (#523/#1345), CMP-029 skeleton";

test.describe("switching (US-CHART-005)", () => {
  test.fixme(true, `blocked: ${BLOCKED_UI}`);
  test("symbol switch keeps GL context id and never shows an empty grid", async ({ page }) => {
    const probe = new ChartProbe(page);
    await page.goto("/chart/BTCUSDT");
    const { glContextId } = await probe.diagnostics();
    await page.keyboard.press("Control+K");
    await page.getByRole("combobox").fill("ETHUSDT");
    await page.keyboard.press("Enter");
    expect((await probe.diagnostics()).glContextId).toBe(glContextId);
  });
  test("hotkey timeframe switch preserves visible-window centre without empty flash", async () => {});
});
