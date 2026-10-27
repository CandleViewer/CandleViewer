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

for (const [name, appearance] of THEMES)
  for (const role of ["owner", "viewer"] as const)
    test(`E10-S01 chrome in ${name} for ${role}: badge visible, no serious axe violation`, async ({
      page,
    }) => {
      await stubSession(page, { role });
      await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({ appearance })));
      await page.goto("/journal");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute("data-theme", name);
      await expect(page.getByRole("img", { name: "Trading environment: Demo" })).toBeVisible();
      // The chrome only: the routed screens are judged by the a11y gate's own collectors. Each
      // target must exist, so an include that matches nothing cannot pass silently.
      const CHROME = ["header", 'nav[aria-label="Primary"]', "aside", "footer"] as const;
      let axe = new AxeBuilder({ page }).withTags([...AXE_GATE_TAGS]);
      for (const target of CHROME) {
        await expect(page.locator(target), target).toHaveCount(1);
        axe = axe.include(target);
      }
      const res = await axe.analyze();
      const blocking = res.violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
      expect(
        blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
      ).toEqual([]);
    });
