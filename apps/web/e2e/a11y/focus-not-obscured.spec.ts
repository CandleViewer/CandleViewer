import { expect, test, type Page } from "@playwright/test";
import { json } from "../support/api";
import { openScreen } from "./open";
import { SIGNED_IN_SCREENS } from "./screens";

// E47-S05 (#1319), Gherkin "A focused control is never hidden" (WCAG 2.4.11): Tab through a signed-in
// screen at 200 % zoom (the 1280 x 800 frame is 640 x 400 CSS px) in both densities, and every
// focused control stays at least partly visible: not fully covered by the sticky header, the status
// bar or anything else. The API is stubbed at the network layer (C-13.5).

const ZOOM_200 = { width: 640, height: 400 };
const MAX_TABS = 60;

interface Probe {
  readonly tag: string;
  readonly inMain: boolean;
  readonly visiblePoints: number;
}

/** The focused element and how many of five sample points inside its box hit it (or its content). */
const probe = (page: Page): Promise<Probe | null> =>
  page.evaluate(() => {
    const el = document.activeElement;
    if (el === null || el === document.body) return null;
    const r = el.getBoundingClientRect();
    const xs = [0.1, 0.5, 0.9];
    const pts = [
      [0.5, 0.5],
      [xs[0], 0.1],
      [xs[2], 0.1],
      [xs[0], 0.9],
      [xs[2], 0.9],
    ] as const;
    const hit = (fx: number | undefined, fy: number): boolean => {
      const x = r.left + r.width * (fx ?? 0.5);
      const y = r.top + r.height * fy;
      if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false;
      const top = document.elementFromPoint(x, y);
      return top !== null && (el.contains(top) || top.contains(el));
    };
    return {
      tag: `${el.tagName.toLowerCase()}${el.id === "" ? "" : `#${el.id}`}`,
      inMain: el.closest("main") !== null,
      visiblePoints: pts.filter(([fx, fy]) => hit(fx, fy)).length,
    };
  });

for (const density of ["compact", "comfortable"] as const) {
  for (const screen of SIGNED_IN_SCREENS) {
    test(`${screen.id} at 200% zoom, ${density}: no focused control is fully obscured`, async ({
      page,
    }) => {
      await page.setViewportSize(ZOOM_200);
      await openScreen(page, screen);
      // Registered after the screen's stubs, so it answers first.
      await page.route("**/api/v1/me/preferences", (r) =>
        r.fulfill(
          json({ appearance: { density: density === "compact" ? "compact" : "comfortable" } }),
        ),
      );
      await page.reload();
      await expect(page.getByRole("main").first()).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute("data-density", density);

      let inMain = 0;
      for (let i = 0; i < MAX_TABS; i++) {
        await page.keyboard.press("Tab");
        const p = await probe(page);
        if (p === null) continue;
        expect(
          p.visiblePoints,
          `${screen.id} ${density}: ${p.tag} is fully obscured`,
        ).toBeGreaterThan(0);
        if (p.inMain) inMain += 1;
      }
      expect(inMain, `${screen.id}: the walk reached nothing in main`).toBeGreaterThan(0);
    });
  }
}
