import { expect, test, type Page } from "@playwright/test";
import { openScreen, STEP_TIMEOUT_MS } from "./open";
import { missingRegions, PUBLIC_REGIONS, SHELL_REGIONS, SHELL_RING } from "./regions";
import { SCREENS, SIGNED_IN_SCREENS } from "./screens";

// E47-S05 (#1319), Gherkin "Regions are reachable and named" (WCAG 2.4.1, 1.3.1): every built screen
// exposes its named regions in the ARIA tree, and on a shell screen Ctrl+\ walks them in order and
// wraps. The API is stubbed at the network layer (C-13.5).

const MAX_PRESSES = 12;

const focusedRegion = (page: Page): Promise<string | null> =>
  page.evaluate(() => {
    const el = document.activeElement;
    if (el === null) return null;
    const role = el.getAttribute("role");
    if (role !== null) return role;
    const map: Record<string, string> = {
      HEADER: "banner",
      NAV: "navigation",
      MAIN: "main",
      ASIDE: "complementary",
      FOOTER: "contentinfo",
    };
    return map[el.tagName] ?? null;
  });

for (const screen of [...SCREENS, ...SIGNED_IN_SCREENS]) {
  test(`${screen.id}: its named regions are in the tree`, async ({ page }) => {
    await openScreen(page, screen);
    const tree = await page.locator("body").ariaSnapshot({ timeout: STEP_TIMEOUT_MS });
    const expected = screen.signedIn ? SHELL_REGIONS : PUBLIC_REGIONS;
    expect(missingRegions(tree, expected), `${screen.id}: regions missing from the tree`).toEqual(
      [],
    );
  });
}

for (const screen of SIGNED_IN_SCREENS) {
  test(`${screen.id}: Ctrl+\\ visits every region in order and wraps`, async ({ page }) => {
    await openScreen(page, screen);
    // From the page: the first region, then each next; the sequence ends where it began (a wrap).
    const seen: (string | null)[] = [];
    for (let i = 0; i < MAX_PRESSES; i++) {
      await page.keyboard.press("Control+\\");
      seen.push(await focusedRegion(page));
      if (i > 0 && seen[i] === seen[0]) break;
    }
    expect(seen.at(-1), "the ring never wrapped").toBe(seen[0]);
    // A region inside `main` (a labelled section) is visited too; the shell's five keep their order.
    expect(seen.slice(0, -1).filter((r) => SHELL_RING.includes(r ?? ""))).toEqual([...SHELL_RING]);
  });
}
