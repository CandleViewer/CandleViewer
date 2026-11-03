// E11-Q02 (#444, AC1). SCR-043 and the scale lock without a pointer (E11-Q01-C03 step 5, C04; PG07):
// the menu opens with Shift+F10 from the focused chart, a mode is chosen with the keyboard, the lock
// badge appears and Enter on it restores auto. Focus returns to the invoker on every close (E47-D04
// R-7). Items are focused through the accessibility tree.
import type { EngineHarness } from "../../../support/engine/harness";
import { test, expect } from "../../../support/engine/nav-guard";

const MENU = { name: "Price scale menu" } as const;
const figure = (h: EngineHarness) => h.chart.getByRole("figure", { name: "Engine harness chart" });

test.describe("scale menu by keyboard (E11-Q01-C03, C04; PG07; R-7) @candidate", () => {
  test.beforeEach(async ({ harness }) => {
    await harness.open("btcusdt-1m-100k");
    await harness.settle();
    await harness.focusChart();
  });

  test("Shift+F10 opens the menu, Enter picks a mode, Escape closes it", async ({
    harness,
    page,
  }) => {
    await page.keyboard.press("Shift+F10");
    await expect(page.getByRole("menu", MENU)).toBeVisible();
    await page.getByRole("menuitemradio", { name: "Percent" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("menu", MENU)).toHaveCount(0);
    await expect(figure(harness)).toBeFocused(); // R-7: back to the invoker
    await page.keyboard.press("Shift+F10");
    await expect(page.getByRole("menuitemradio", { name: "Percent" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu", MENU)).toHaveCount(0);
    await expect(figure(harness)).toBeFocused(); // R-7 again, on Escape
  });

  test("Lock scale shows the badge and Enter on the badge restores auto", async ({
    harness,
    page,
  }) => {
    await page.keyboard.press("Shift+F10");
    await page.getByRole("menuitemcheckbox", { name: "Lock scale" }).focus();
    await page.keyboard.press("Enter");
    const badge = harness.chart.getByRole("button", { name: "Price scale locked" });
    await expect(badge).toBeVisible();
    await badge.focus();
    await page.keyboard.press("Enter");
    await expect(badge).toHaveCount(0);
  });
});
