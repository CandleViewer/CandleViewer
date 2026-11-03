// E11-Q02 (#444, AC1, BQ-07): the keyboard-only specs (nav-only/) prove no pointer was used. An init
// script installs capture-phase listeners for every pointer-class event on `window` before the page
// loads, and the fixture fails the spec at teardown if any fired. Untrusted (dispatched) events count
// too: a script-dispatched pointer event is as much a pointer path as a real one. A lint rule bans the
// pointer APIs in `nav-only/*.spec.ts` as well. (The folder is not named after keys: C-10.2's `*key*`
// path rule would send test files to security review.) A local guard: #1356's is not on main yet.
import { expect, test as base } from "./test";

const POINTER_EVENTS = [
  "pointerdown",
  "pointermove",
  "pointerup",
  "pointercancel",
  "mousedown",
  "mousemove",
  "mouseup",
  "touchstart",
  "touchmove",
  "touchend",
  "wheel",
  "dblclick",
] as const; // `click` and `contextmenu` are left out: Enter and Shift+F10 raise them without a pointer

declare global {
  interface Window {
    __pointerEvents?: string[];
  }
}

export const test = base.extend<{ pointerGuard: undefined }>({
  pointerGuard: [
    async ({ page }, use) => {
      await page.addInitScript((types) => {
        const seen: string[] = [];
        window.__pointerEvents = seen;
        for (const t of types) window.addEventListener(t, () => seen.push(t), true);
      }, POINTER_EVENTS);
      await use(undefined);
      expect(await page.evaluate(() => window.__pointerEvents ?? ["guard missing"])).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
