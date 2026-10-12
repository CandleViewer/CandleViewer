import { test, expect } from "@playwright/test";

// E12-Q03 (#419). All cases are fixme: the chart workspace route, CMP-220/222, SCR-041/042/045/046
// do not exist in apps/web yet. Un-fixme when the blocker named on each case lands.
const BLOCKED_UI = "SCR-047/SCR-048 (#329 design), days-to-load control";

test.describe("history states (US-CHART-010, US-MKT-008)", () => {
  test.fixme(true, `blocked: ${BLOCKED_UI}`);
  test("503 on /market/klines shows SCR-048 with retry and reason, not an empty chart", async ({
    page,
  }) => {
    await page.route("**/market/klines*", (r) => r.fulfill({ status: 503, body: "{}" }));
    await page.goto("/chart/BTCUSDT");
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("button", { name: /retry/i })).toBeVisible();
  });
  test("422 no_data_recorded shows SCR-047 naming the first available timestamp", async ({
    page,
  }) => {
    await page.route("**/market/klines*", (r) =>
      r.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ code: "no_data_recorded" }),
      }),
    );
    await page.goto("/chart/BTCUSDT");
    await expect(page.getByText(/first available/i)).toBeVisible();
  });
});
