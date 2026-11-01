import { test, expect } from "@playwright/test";
import { stubSession } from "./support/api";

// E10-Q03 (#302) F-6 (SC 1.4.10): 400 % zoom on a 1280 x 1024 window is a 320 x 256 CSS px viewport. The wrapped
// TopBar and the StatusBar used to leave `main` no height there, so the rail, the workspace and the drawer were
// all 0 px tall and unreachable; the shell now grows with its content and the page scrolls vertically.
test("E10-Q03 reflow at 320 x 256 CSS px: rail, workspace and drawer keep a height, no horizontal scroll", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 256 });
  await stubSession(page, { role: "owner" });
  await page.goto("/journal");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  for (const target of ['nav[aria-label="Primary"]', "main", 'aside[aria-label="Side panels"]']) {
    const box = await page.locator(target).boundingBox();
    expect(box?.height ?? 0, `${target} height`).toBeGreaterThanOrEqual(200);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    ),
  ).toBe(false);
  // the launcher can be reached and used at this size
  await page.getByRole("button", { name: "Notifications" }).click();
  await expect(page.getByRole("group", { name: "Notifications" })).toBeVisible();
});

const REM = 16;
const boxes = (page: import("@playwright/test").Page) =>
  Promise.all(
    ['nav[aria-label="Primary"]', "main", 'aside[aria-label="Side panels"]'].map(async (sel) => ({
      sel,
      box: await page.locator(sel).boundingBox(),
    })),
  );
const canvasOverflow = (page: import("@playwright/test").Page) =>
  page.locator("[data-shell-canvas]").evaluate((el) => getComputedStyle(el).overflowY);

// Normal size: the narrow styles do not leak (the frame is one viewport tall, the canvas scrolls itself). Known
// body-margin overshoot: A11Y-F-0035 (nothing resets the default 8 px body margin, so the 100vh frame overshoots).
const overshoot = (page: import("@playwright/test").Page) =>
  page.evaluate(
    () => document.documentElement.scrollHeight - document.documentElement.clientHeight,
  );
async function openNormal(page: import("@playwright/test").Page): Promise<void> {
  await page.setViewportSize({ width: 1280, height: 800 });
  await stubSession(page, { role: "owner" });
  await page.goto("/journal");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

test("E10-Q03 normal size 1280 x 800: the narrow styles don't leak; known body-margin overshoot A11Y-F-0035", async ({
  page,
}) => {
  await openNormal(page);
  const [nav, main, aside] = await boxes(page);
  const header = await page.getByRole("banner").boundingBox();
  const footer = await page.getByRole("contentinfo").boundingBox();
  const chrome = (header?.height ?? 0) + (footer?.height ?? 0);
  expect(Math.abs((main?.box?.height ?? 0) - (800 - chrome))).toBeLessThanOrEqual(2);
  for (const b of [nav, aside]) expect(b?.box?.height ?? 0, b?.sel).toBeGreaterThanOrEqual(400);
  // The tracked bound: the overshoot is the body margin (2 x 8 px), no more. Fixing A11Y-F-0035 must tighten it
  // to 0 (and flips the strict test below to passing).
  expect(await overshoot(page)).toBeLessThanOrEqual(16);
  expect(await canvasOverflow(page)).toBe("auto");
});

// Strict form of the same claim: the main screen has no page-level vertical scroll. It fails today (A11Y-F-0035);
// `test.fail` makes the fix of the body margin flip it to a pass, at which point remove the `fail`.
test("E10-Q03 normal size 1280 x 800: no page-level scroll (A11Y-F-0035, expected to fail until fixed)", async ({
  page,
}) => {
  test.fail(true, "A11Y-F-0035: the default 8 px body margin plus the 100vh frame");
  await openNormal(page);
  expect(await overshoot(page)).toBe(0);
});

// 1280 x 400 is wide but short: it matches useReflow's (max-height: 25rem), so the narrow branch applies. `main` keeps
// at least the 16rem minimum, nothing is 0 px, and the page (not the canvas) scrolls.
test("E10-Q03 wide but short 1280 x 400: main keeps its 16rem minimum, the page scrolls, nothing is 0 px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 400 });
  await stubSession(page, { role: "owner" });
  await page.goto("/journal");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  for (const { sel, box } of await boxes(page)) {
    expect(box?.height ?? 0, `${sel} height`).toBeGreaterThanOrEqual(16 * REM - 1);
  }
  expect(await canvasOverflow(page)).toBe("visible");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    ),
  ).toBe(false);
});
