import { mkdirSync, writeFileSync } from "node:fs";
import { test } from "@playwright/test";
import { skippedAlertEntries } from "./alert-surfaces";
import { REPORT_DIR, SCREENS } from "./screens";

const MAX_TABS = 80;

interface Step {
  name: string;
  ok: boolean;
}

interface MouseWindow {
  __mouse: number;
}

// mousemove is deliberately not counted: the browser synthesises it after layout
// shifts (#2063). Untrusted clicks (e.g. Radix .click()) ARE counted on purpose.
// Gate 4 collector: keyboard-only traversal. It never dispatches a pointer
// event; an init-script counter records any mouse event so the gate can prove
// none occurred. The s8.2 order/symbol/table tasks are added by their screen
// tickets as further steps; today the placeholder screens are traversed.
test("collect keyboard", async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as MouseWindow).__mouse = 0;
    for (const t of ["mousedown", "mouseup", "click"]) {
      window.addEventListener(
        t,
        () => {
          (window as unknown as MouseWindow).__mouse += 1;
        },
        true,
      );
    }
  });
  const steps: Step[] = [];
  let mouseEvents = 0;
  const perScreen: Record<string, number> = {};
  for (const s of SCREENS) {
    await page.goto(s.path);
    await page.getByRole("main").first().waitFor();
    let seen = 0;
    let stuck = 0;
    let prev = "";
    let focusVisible = true;
    for (let i = 0; i < MAX_TABS; i++) {
      await page.keyboard.press("Tab");
      const info = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return { key: "<body>", visible: true };
        const cs = getComputedStyle(el);
        const visible =
          (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) ||
          cs.boxShadow !== "none";
        return { key: `${el.tagName}#${el.id}:${(el.textContent ?? "").slice(0, 20)}`, visible };
      });
      if (info.key === "<body>") {
        if (seen > 0) break; // wrapped past the last tab stop: no trap
        continue;
      }
      if (!info.visible) focusVisible = false;
      stuck = info.key === prev ? stuck + 1 : 0;
      prev = info.key;
      if (stuck >= 3) break;
      seen += 1;
    }
    steps.push({ name: `${s.id} tab-traversal-no-trap`, ok: stuck < 3 });
    steps.push({ name: `${s.id} visible-focus-indicator`, ok: focusVisible });
    const n = await page.evaluate(() => (window as unknown as MouseWindow).__mouse);
    perScreen[s.id] = n;
    mouseEvents += n;
  }
  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(
    `${REPORT_DIR}/keyboard.json`,
    JSON.stringify({ mouseEvents, perScreen, steps, skipped: skippedAlertEntries() }, null, 2),
  );
});
