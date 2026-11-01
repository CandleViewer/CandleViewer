import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { json, stubSession } from "./support/api";
import { AXE_GATE_TAGS } from "./a11y/tags";
import { RAIL } from "./support/rail";

// E10-S01 (#304) S9: the shell chrome end to end. Sign in, then three routes through the nav rail:
// `aria-current` moves with the route, the environment badge is announced on each change, the skip
// link is the first Tab stop and every page has one `main`. The API is stubbed at the network layer
// (C-13.5); the app code is not mocked.

type Role = "owner" | "manager" | "viewer";

/** Three rail items every role has, with the path each lands on (Settings opens its default tab). */
const ROUTES = [
  ["Journal", /\/journal$/u],
  ["Replay", /\/replay$/u],
  ["Settings", /\/settings(\/|$)/u],
] as const;

const rail = (page: Page) => page.getByRole("navigation", { name: "Primary" });

/** The shell announcer's polite message: a new `<p data-seq>` per message (`announcer.tsx`). */
const polite = (page: Page) =>
  page.evaluate(() => {
    const p = document.querySelector('[aria-live="polite"][aria-atomic="true"] > p[data-seq]');
    return p === null ? null : { seq: Number(p.getAttribute("data-seq")), text: p.textContent };
  });

async function signIn(page: Page, role: Role): Promise<void> {
  await stubSession(page, { role });
  await page.route("**/api/v1/auth/login", (r) => r.fulfill(json({ status: "authenticated" })));
  await page.goto("/login");
  await page.getByLabel("Username or email").fill("ann");
  await page.getByLabel("Password", { exact: true }).fill("pw-e2e");
  await page.getByRole("button", { name: "Sign in" }).click();
  // R-100 `/terminal` redirects to the last-used layout (`12-sitemap.md` R-100).
  await expect(page).toHaveURL(/\/terminal\/last$/u);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

for (const role of ["owner", "manager", "viewer"] as const) {
  test(`E10-S01 ${role}: sign in, then three routes through the rail`, async ({ page }) => {
    await signIn(page, role);

    // Keyboard entry on a freshly loaded route, not after a route change: reload, then nothing
    // holds focus until the first Tab, which lands on the skip link; it moves focus to `main`.
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true);
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
    await expect(page.getByRole("main")).toHaveCount(1);

    // Role variance is structural: only the role's items are links; Admin is absent for non-owners.
    await expect(rail(page).getByRole("link")).toHaveText([...RAIL[role]]);
    if (role !== "owner") await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
    await expect(rail(page).getByRole("link", { name: "Terminal" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    for (const [label, path] of ROUTES) {
      // The baseline is read once the previous step's assertions held, so an earlier announcement
      // (the sign-in redirect's, the last step's) can never satisfy this step's check.
      const before = (await polite(page))?.seq ?? 0;
      await rail(page).getByRole("link", { name: label, exact: true }).click();
      await expect(page).toHaveURL(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
      const current = rail(page).locator('[aria-current="page"]');
      await expect(current).toHaveCount(1);
      await expect(current).toHaveText(label);
      await expect(page.getByRole("main")).toHaveCount(1);
      // The environment badge is announced once per route change, and stays visible in the top bar.
      await expect.poll(async () => (await polite(page))?.seq ?? 0).toBeGreaterThan(before);
      expect((await polite(page))?.text).toBe("Trading environment: Demo");
      await expect(
        page.getByRole("banner").getByRole("img", { name: "Trading environment: Demo" }),
      ).toBeVisible();
    }
  });
}

/** The preference the server holds → the root's `data-theme` the theme runtime writes. */
const THEMES = [
  ["dark", { theme: "dark" }],
  ["light", { theme: "light" }],
  ["high-contrast", { theme: "dark", high_contrast: true }],
] as const;

// E10-Q03: both densities, and every impact level counts (E10-S01 counted serious/critical at one density).
for (const [name, appearance] of THEMES)
  for (const density of ["compact", "comfortable"] as const)
    for (const role of ["owner", "viewer"] as const)
      test(`E10-S01 chrome in ${name}/${density} for ${role}: badge visible, no axe violation of any impact`, async ({
        page,
      }) => {
        await stubSession(page, { role });
        await page.route("**/api/v1/me/preferences", (r) =>
          r.fulfill(json({ appearance: { ...appearance, density } })),
        );
        await page.goto("/journal");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute("data-theme", name);
        await expect(page.locator("html")).toHaveAttribute("data-density", density);
        await expect(page.getByRole("img", { name: "Trading environment: Demo" })).toBeVisible();
        // The chrome only: the routed screens are judged by the a11y gate's own collectors. Each
        // target must exist, so an include that matches nothing cannot pass silently.
        const CHROME = ["header", 'nav[aria-label="Primary"]', "aside", "footer"] as const;
        // Two scans, every impact counted: the gate's tags, then the best-practice rules (region, heading-order).
        const scan = (): AxeBuilder => {
          let axe = new AxeBuilder({ page });
          for (const target of CHROME) axe = axe.include(target);
          return axe;
        };
        for (const target of CHROME) await expect(page.locator(target), target).toHaveCount(1);
        const gate = await scan()
          .withTags([...AXE_GATE_TAGS])
          .analyze();
        const practice = await scan()
          .options({ runOnly: { type: "tag", values: ["best-practice"] } })
          .analyze();
        const res = { violations: [...gate.violations, ...practice.violations] };
        expect(
          res.violations.map(
            (v) => `${v.impact}/${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
          ),
        ).toEqual([]);
      });

// E10-Q03 (Gherkin 3): a LIVE session says so, once per route change, politely.
test("E10-Q03 LIVE session: the badge names Live and each route change announces it once", async ({
  page,
}) => {
  await stubSession(page, { role: "owner" });
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "live", elevated_until: null },
      }),
    ),
  );
  await page.goto("/journal");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(
    page.getByRole("banner").getByRole("img", { name: "Trading environment: Live" }),
  ).toBeVisible();
  const before = (await polite(page))?.seq ?? 0;
  await rail(page).getByRole("link", { name: "Replay", exact: true }).click();
  await expect(page).toHaveURL(/\/replay$/u);
  await expect.poll(async () => (await polite(page))?.seq ?? 0).toBe(before + 1);
  expect((await polite(page))?.text).toBe("Trading environment: Live");
  // not again for a re-render: the sequence stays put
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
  expect((await polite(page))?.seq).toBe(before + 1);
});

// E10-Q03 (Gherkin 2): each overlay's Esc closes it and returns focus to what opened it.
test("E10-Q03 Esc closes the cheatsheet and the drawer and returns focus to their trigger", async ({
  page,
}) => {
  await stubSession(page, { role: "owner" });
  await page.goto("/journal");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  const drawerButton = page.getByRole("button", { name: "Notifications" });
  await page.keyboard.press("Shift"); // keyboard modality: the launcher's focus is :focus-visible
  await drawerButton.focus();
  await page.keyboard.press("Enter");
  await expect(drawerButton).toHaveAttribute("aria-expanded", "true");
  // The launcher's own CMP-016 tooltip is showing (keyboard focus) and takes the first Esc, as the
  // APG tooltip pattern says (the topmost layer takes it); the second closes the drawer.
  await page.keyboard.press("Escape");
  await expect(drawerButton).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator('[role="tooltip"]:not([hidden])')).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(drawerButton).toHaveAttribute("aria-expanded", "false");
  await expect(drawerButton).toBeFocused();

  const toggle = rail(page).getByRole("button", { name: /navigation rail$/u });
  await toggle.focus();
  await page.keyboard.press("Control+/");
  const sheet = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(sheet).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await expect(toggle).toBeFocused();
});

// E10-Q03 fix 1: the collapsed rail's name, badge and key show on keyboard focus (SC 1.4.13), Esc keeps
// focus, and nothing is read twice (the echo is aria-hidden; the link keeps its own name).
test("E10-Q03 collapsed rail: the CMP-016 echo shows on keyboard focus and Esc hides it", async ({
  page,
}) => {
  await stubSession(page, { role: "owner" });
  await page.goto("/journal");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const toggle = rail(page).getByRole("button", { name: /navigation rail$/u });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Shift"); // keyboard modality: the next focus is :focus-visible
  const link = rail(page).getByRole("link", { name: "Journal", exact: true });
  await link.focus();
  const echo = page.locator('[role="tooltip"]:not([hidden])');
  await expect(echo).toHaveText(/^Journal · Alt\+\d$/u);
  await expect(echo).toHaveAttribute("aria-hidden", "true");
  await expect(link).not.toHaveAttribute("title");
  await page.keyboard.press("Escape");
  await expect(echo).toHaveCount(0);
  await expect(link).toBeFocused();
  // expanded again: no echo at all
  await toggle.click();
  await link.focus();
  await expect(page.locator('[role="tooltip"]:not([hidden])')).toHaveCount(0);
});

// #304 S10 (A11Y-F-0016, SC 1.4.10): at 320 CSS px the rail is collapsed by default, and expanded it
// is an overlay over `main` (the drawer pattern), never a column: `main` keeps its width either way.
test("E10-S01 reflow at 320 CSS px: the rail collapses, and expands over main", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await stubSession(page, { role: "owner" });
  await page.goto("/journal");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const toggle = rail(page).getByRole("button", { name: /navigation rail$/u });
  const mainWidth = () => page.getByRole("main").evaluate((m) => m.getBoundingClientRect().width);
  const scrolls = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );

  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  const collapsed = await mainWidth();
  expect(collapsed).toBeGreaterThanOrEqual(200);
  expect(await scrolls()).toBe(false);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(await mainWidth()).toBe(collapsed); // drawn over main, not beside it
  expect(await scrolls()).toBe(false);
  await page.keyboard.press("Escape");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(toggle).toBeFocused();
  // the stored choice is untouched: the overlay is this page's only
  expect(await page.evaluate(() => localStorage.getItem("cv.shell.layout.v1"))).toBeNull();
});
