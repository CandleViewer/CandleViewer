import { test, expect } from "@playwright/test";

// E12-Q03 (#419). All cases are fixme: the chart workspace route, CMP-220/222, SCR-041/042/045/046
// do not exist in apps/web yet. Un-fixme when the blocker named on each case lands.
const BLOCKED_UI = "SCR-042 (#201) rebuild progress UI, E12-S03 UI wiring";

test.describe("range/delta/renko (US-CHART-004)", () => {
  test.fixme(true, `blocked: ${BLOCKED_UI}`);
  test("renko rebuild shows progress, cancel keeps the previous series", async ({ page }) => {
    await page.goto("/chart/BTCUSDT?mode=renko");
    await expect(page.getByRole("progressbar", { name: /rebuilding/i })).toBeVisible();
    await page.getByRole("button", { name: "Cancel" }).click();
  });
  test("Heikin-Ashi + footprint surfaces the documented guard message", async ({ page }) => {
    await page.goto("/chart/BTCUSDT");
    await expect(page.getByRole("alert")).toBeVisible();
  });
});
