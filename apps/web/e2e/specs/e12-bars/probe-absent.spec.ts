import { test, expect } from "@playwright/test";

// E12-Q03 security note: the diagnostics JSON island is test-only and must not ship in the
// production bundle served by `vite preview`. Runs today (vacuously true until the probe exists)
// so it guards the moment it lands.
test("production build exposes no chart diagnostics probe", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByTestId("chart-diagnostics-json")).toHaveCount(0);
});
