import { type Locator, type Page } from "@playwright/test";
import { expect, packTest as test } from "./ga/fixtures";

// E47-S04 AC1 e2e (#1318): "Reduced motion is honoured everywhere". With the OS asking for reduced
// motion and no saved preference, the real shell resolves `data-motion="reduce"` and the animated
// surfaces on main (the nav rail's labels, the Notifications panel, the toast) show no motion, while
// still showing their content. A control case without emulation shows the full-motion values, so the
// reduce assertions cannot pass vacuously. The session is stubbed at the network layer; app code is
// not mocked. The heatmap and bubbles are not built yet, so they have no case here.
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
});

async function openTerminal(page: Page): Promise<void> {
  await page.goto("/terminal");
  await expect(page).toHaveURL(/\/terminal\/last$/);
  await expect(page.getByRole("main")).toBeVisible();
}

interface Motion {
  /** The inline `transition` the component sets ("" when it sets none). */
  readonly inline: string;
  /** Computed `transition-duration`, in seconds, one per transitioned property. */
  readonly durations: readonly number[];
  readonly animationName: string;
}

const motionOf = (el: Locator): Promise<Motion> =>
  el.evaluate((node) => {
    const style = getComputedStyle(node);
    const seconds = (t: string): number =>
      t.endsWith("ms") ? parseFloat(t) / 1000 : parseFloat(t);
    return {
      inline: (node as HTMLElement).style.transition,
      durations: style.transitionDuration.split(",").map((t) => seconds(t.trim())),
      animationName: style.animationName,
    };
  });

/** Effectively instant: `theme.css` clamps to 0.01 ms under reduce. */
const INSTANT = 0.001;

const railLabel = (page: Page) =>
  page
    .getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: "Journal" })
    .getByText("Journal", { exact: true });
const panel = (page: Page) => page.getByRole("group", { name: "Notifications" });

test.describe("OS asks for reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("the root resolves data-motion=reduce from the OS when no preference is saved @ga-regression @ga-area-shell @story-US-SET-007", async ({
    page,
  }) => {
    await openTerminal(page);
    await expect(page.locator("html")).toHaveAttribute("data-motion", "reduce");
  });

  test("collapsing the nav rail moves its labels with no transition and keeps their names @ga-regression @ga-area-shell @story-US-SET-007", async ({
    page,
  }) => {
    await openTerminal(page);
    await page.getByRole("button", { name: "Collapse navigation rail" }).click();
    await expect(page.getByRole("button", { name: "Expand navigation rail" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    const label = railLabel(page);
    const motion = await motionOf(label);
    expect(motion.inline).toBe("none");
    expect(Math.max(...motion.durations)).toBeLessThanOrEqual(INSTANT);
    // The end state is already in force: no fade in progress.
    await expect(label).toHaveCSS("opacity", "0");
    // Reduce removes motion, not information: the item is still a named link.
    await expect(
      page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Journal" }),
    ).toBeVisible();
  });

  test("opening the Notifications panel shows it with no transition @ga-regression @ga-area-shell @story-US-SET-007", async ({
    page,
  }) => {
    await openTerminal(page);
    await page.getByRole("button", { name: "Notifications" }).click();
    await expect(page.getByRole("button", { name: "Notifications" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await expect(panel(page)).toBeVisible();
    const motion = await motionOf(panel(page));
    expect(motion.inline).toBe("none");
    expect(Math.max(...motion.durations)).toBeLessThanOrEqual(INSTANT);
  });

  test("a toast appears with its text and no animation @ga-regression @ga-area-shell @story-US-SET-007", async ({
    page,
  }) => {
    await openTerminal(page);
    await expect(page.getByTestId("toast-host")).toBeAttached();
    await page.keyboard.press("Control+Shift+X"); // an inert chord: the shell explains it in a toast
    // SCR-015 renders through ToastRegion (#5215): the stack is the Notifications region, a toast its group.
    const toast = page.getByRole("region", { name: "Notifications" }).getByRole("group").first();
    await expect(toast).toContainText("Cancel all working orders for symbol is not available");
    const motion = await motionOf(toast);
    expect(motion.animationName).toBe("none");
    expect(Math.max(...motion.durations)).toBeLessThanOrEqual(INSTANT);
  });
});

test.describe("no reduced-motion request (control)", () => {
  test.use({ reducedMotion: "no-preference" });

  test("the root is not reduced and the same surfaces carry real transitions @ga-regression @ga-area-shell", async ({
    page,
  }) => {
    await openTerminal(page);
    await expect(page.locator("html")).not.toHaveAttribute("data-motion", "reduce");

    await page.getByRole("button", { name: "Collapse navigation rail" }).click();
    const label = await motionOf(railLabel(page));
    expect(label.inline).toContain("transform");
    expect(label.inline).toContain("opacity");
    expect(Math.min(...label.durations)).toBeGreaterThan(INSTANT);

    await page.getByRole("button", { name: "Notifications" }).click();
    await expect(panel(page)).toBeVisible();
    const drawer = await motionOf(panel(page));
    expect(drawer.inline).toContain("transform");
    expect(Math.max(...drawer.durations)).toBeGreaterThan(INSTANT);
  });

  test("the same toast carries its entry animation @ga-regression @ga-area-shell", async ({
    page,
  }) => {
    await openTerminal(page);
    await expect(page.getByTestId("toast-host")).toBeAttached();
    await page.keyboard.press("Control+Shift+X");
    const toast = page.getByRole("region", { name: "Notifications" }).getByRole("group").first();
    await expect(toast).toContainText("Cancel all working orders for symbol is not available");
    // The toast enters by a CSS animation (the toast-in recipe), not a transition, so its name is the signal.
    expect((await motionOf(toast)).animationName).not.toBe("none");
  });
});
