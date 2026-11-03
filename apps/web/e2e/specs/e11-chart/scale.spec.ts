// E11-Q02 (#444). The scale lock through the price axis, as a user does it (E11-Q01-C03), and the
// fixtures' sanity (C33, C35). The lock shows as the host-DOM button "Price scale locked"
// (scale-badge.ts); the state itself is not a public event, so the badge is the evidence.
import { flick } from "../../support/engine/flick";
import type { EngineHarness } from "../../support/engine/harness";
import { expect, test } from "../../support/engine/test";

const BADGE = { name: "Price scale locked" } as const;

test.describe("price scale (E11-Q01-C03) @candidate", () => {
  test("dragging the price axis locks it; a double-click on the axis restores auto", async ({
    page,
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k");
    const axis = await harness.at("price", 30, 100);
    await flick(page, axis, { dx: 0, dy: 80 }, 300, 2);
    await expect(harness.chart.getByRole("button", BADGE)).toBeVisible();
    await page.mouse.dblclick(axis.x, axis.y);
    await expect(harness.chart.getByRole("button", BADGE)).toHaveCount(0);
  });

  test("activating the badge with Enter restores auto", async ({ page, harness }) => {
    await harness.open("btcusdt-1m-100k");
    const axis = await harness.at("price", 30, 100);
    await flick(page, axis, { dx: 0, dy: 80 }, 300, 2);
    const badge = harness.chart.getByRole("button", BADGE);
    await badge.focus();
    await page.keyboard.press("Enter");
    await expect(badge).toHaveCount(0);
  });

  for (const fixture of ["synthetic-flat", "synthetic-nonpositive"] as const) {
    test(`${fixture} loads without an engine error (C33, C35)`, async ({ harness }) => {
      await harness.open(fixture);
      await harness.settle();
      expect(await harness.count("error")).toBe(0);
    });
  }

  // SCR-043 is mounted in the harness (apps/web `<PriceScaleMenu>`), so these drive the real menu.
  const menuItem = (harness: EngineHarness, name: string) =>
    harness.page.getByRole("menuitemradio", { name });

  async function openMenu(harness: EngineHarness): Promise<void> {
    const gutter = await harness.at("price", 30, 100);
    await harness.page.mouse.click(gutter.x, gutter.y, { button: "right" });
    await expect(harness.page.getByRole("menu", { name: "Price scale menu" })).toBeVisible();
  }

  test("each scale mode is reachable through the menu and is what the menu then reports (C05, C06)", async ({
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k");
    for (const mode of ["Logarithmic", "Percent", "Indexed to 100", "Linear"]) {
      await openMenu(harness);
      await menuItem(harness, mode).click();
      await openMenu(harness);
      await expect(menuItem(harness, mode)).toHaveAttribute("aria-checked", "true");
      await harness.page.keyboard.press("Escape");
    }
  });

  test("log is refused on non-positive data, with its reason, and the mode stays (C07)", async ({
    harness,
  }) => {
    await harness.open("synthetic-nonpositive");
    await openMenu(harness);
    const log = menuItem(harness, "Logarithmic");
    await expect(log).toHaveAttribute("aria-disabled", "true");
    await expect(log).toHaveAccessibleDescription(/Log scale needs all-positive values/u);
    await log.click({ force: true });
    await expect(menuItem(harness, "Linear")).toHaveAttribute("aria-checked", "true");
  });
});
