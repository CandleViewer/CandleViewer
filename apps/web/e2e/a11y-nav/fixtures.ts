import { expect, test as base, type Page } from "@playwright/test";
import { guardPage } from "./mouseGuard";

interface PointerWindow {
  __pointerEvents: number;
}

// Pointer events dispatched from inside the page. mousemove is not counted: the browser synthesises it
// after layout shifts (#2063), the same rule as the G004 collector (a11y/keyboard.collect.ts).
const COUNTED = ["mousedown", "mouseup", "click", "pointerdown", "pointerup", "touchstart"];

/**
 * `test` for the a11y-nav project: `page` is the guarded page, and a journey that ends with a counted
 * pointer event in the document fails even if it got past the proxy.
 */
export const test = base.extend<{ page: Page }>({
  page: async ({ page }, use) => {
    await page.addInitScript((types: string[]) => {
      (window as unknown as PointerWindow).__pointerEvents = 0;
      for (const t of types) {
        window.addEventListener(
          t,
          () => {
            (window as unknown as PointerWindow).__pointerEvents += 1;
          },
          true,
        );
      }
    }, COUNTED);
    await use(guardPage(page));
    const n = await page.evaluate(() => (window as unknown as PointerWindow).__pointerEvents);
    expect(n, "A11Y-K002 pointer events seen in the page during a keyboard-only journey").toBe(0);
  },
});

export { expect };
