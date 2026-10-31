import { test, expect, type Page } from "@playwright/test";

// E47-S04 AC3 e2e (#1318), ruling BQ-1 (a): Ctrl+Shift+M flips the resolved motion to an explicit
// on/off, persists it as SCR-117 does (the theme store's localStorage record, `cv.theme.v1`; no
// network write exists for it) and says the new state once, politely. The session is stubbed at
// the network layer; app code is not mocked, so the real auth guard and KeymapHost run.
const THEME_KEY = "cv.theme.v1";
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

test.use({ reducedMotion: "no-preference" });

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
  await page.goto("/terminal");
  await expect(page).toHaveURL(/\/terminal\/last$/);
});

const root = (page: Page) => page.locator("html");
const region = (page: Page) => page.locator("#cv-theme-live-region");
const stored = (page: Page) =>
  page.evaluate((key) => {
    const raw = window.localStorage.getItem(key);
    return raw === null ? null : (JSON.parse(raw) as { motionOverride?: string });
  }, THEME_KEY);

/** Counts the announcements the live region receives: each one replaces its text node. */
async function watchAnnouncements(page: Page): Promise<void> {
  await page.evaluate(() => {
    const el = document.getElementById("cv-theme-live-region");
    if (el === null) throw new Error("no theme live region");
    const w = window as unknown as { __said: string[] };
    w.__said = [];
    new MutationObserver(() => w.__said.push(el.textContent ?? "")).observe(el, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  });
}
const said = (page: Page) =>
  page.evaluate(() => (window as unknown as { __said: string[] }).__said);

test("Ctrl+Shift+M from default motion reduces motion, says so once and persists on", async ({
  page,
}) => {
  await expect(root(page)).not.toHaveAttribute("data-motion", "reduce");
  await watchAnnouncements(page);
  await page.keyboard.press("Control+Shift+M");
  await expect(root(page)).toHaveAttribute("data-motion", "reduce");
  await expect(region(page)).toHaveAttribute("aria-live", "polite");
  await expect(region(page)).toHaveText("Reduced motion on");
  expect(await said(page)).toEqual(["Reduced motion on"]);
  await expect.poll(() => stored(page)).toMatchObject({ motionOverride: "on" });
});

test("a second Ctrl+Shift+M restores full motion, says so once and persists off", async ({
  page,
}) => {
  await page.keyboard.press("Control+Shift+M");
  await expect(root(page)).toHaveAttribute("data-motion", "reduce");
  await watchAnnouncements(page);
  await page.keyboard.press("Control+Shift+M");
  await expect(root(page)).toHaveAttribute("data-motion", "safe");
  await expect(region(page)).toHaveText("Reduced motion off");
  expect(await said(page)).toEqual(["Reduced motion off"]);
  await expect.poll(() => stored(page)).toMatchObject({ motionOverride: "off" });
});

test("a held Ctrl+Shift+M flips once: the auto-repeats do nothing", async ({ page }) => {
  await watchAnnouncements(page);
  await page.keyboard.down("Control");
  await page.keyboard.down("Shift");
  await page.keyboard.down("M"); // first down
  await page.keyboard.down("M"); // already down: Chromium sends it with repeat=true
  await page.keyboard.down("M");
  await page.keyboard.up("M");
  await page.keyboard.up("Shift");
  await page.keyboard.up("Control");
  await expect(root(page)).toHaveAttribute("data-motion", "reduce");
  await expect(region(page)).toHaveText("Reduced motion on");
  expect(await said(page)).toEqual(["Reduced motion on"]);
  await expect.poll(() => stored(page)).toMatchObject({ motionOverride: "on" });
});
