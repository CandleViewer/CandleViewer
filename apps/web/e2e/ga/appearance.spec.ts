import type { Page } from "@playwright/test";
import { stubSession } from "../support/api";
import { expect, test } from "./fixtures";

// E49-Q01 (#1335): US-SET-005 (colour conventions and CVD-safe palettes) on SCR-116, the shipped
// Appearance section of R-203 /settings/appearance, as it ships: the palette and convention
// controls, the per-view legends that state the convention in text and glyph (never hue alone),
// and the root attributes every surface keys off. The chart, DOM, heatmap, footprint, bubble and
// profile surfaces are not mounted yet, so "every surface updates" is asserted at the root (the
// attributes those surfaces read) and in each view's legend; the surfaces join with their epics.

const VIEWS = ["Chart", "Footprint", "DOM ladder", "Heatmap", "Bubbles", "Profile"] as const;
const legend = (page: Page, view: string) =>
  page
    .getByRole("region", { name: "Preview" })
    .getByRole("group", { name: `${view} colour legend` });

test.beforeEach(async ({ page }) => {
  await stubSession(page, { role: "viewer" });
  await page.goto("/settings/appearance");
  await expect(page.getByRole("heading", { level: 1, name: "Appearance" })).toBeVisible();
});

test("@plan-GA-SET-1 the default convention is green for buy and red for sell, stated in every view's legend @ga-regression @ga-area-shell @story-US-SET-005", async ({
  page,
}) => {
  await expect(page.getByRole("radio", { name: "Default (green / red)" })).toBeChecked();
  for (const view of VIEWS) {
    await expect(legend(page, view)).toContainText("Green = buy / bid / up");
    await expect(legend(page, view)).toContainText("Red = sell / ask / down");
    // Direction stays readable without colour: each side carries its own glyph.
    await expect(legend(page, view)).toContainText("▲");
    await expect(legend(page, view)).toContainText("▼");
  }
});

test("@plan-GA-SET-2 a CVD-safe palette and an inverted convention reach every view and persist @ga-regression @ga-area-shell @story-US-SET-005", async ({
  page,
}) => {
  const root = page.locator("html");
  await page.getByRole("radio", { name: "Colour-blind safe (blue / orange)" }).check();
  await expect(page.getByRole("status").filter({ hasText: /^Saved\.$/u })).toBeVisible();
  await expect(root).toHaveAttribute("data-palette", "cvd-safe");
  for (const view of VIEWS) await expect(legend(page, view)).toContainText("Blue = buy / bid / up");

  await page.getByRole("checkbox", { name: "Invert buy/sell colours" }).check();
  await expect(root).toHaveAttribute("data-convention", "inverted");
  for (const view of VIEWS)
    await expect(legend(page, view)).toContainText("Orange = buy / bid / up");

  await page.reload();
  await expect(
    page.getByRole("radio", { name: "Colour-blind safe (blue / orange)" }),
  ).toBeChecked();
  await expect(page.getByRole("checkbox", { name: "Invert buy/sell colours" })).toBeChecked();
  await expect(root).toHaveAttribute("data-palette", "cvd-safe");
  await expect(root).toHaveAttribute("data-convention", "inverted");
});
