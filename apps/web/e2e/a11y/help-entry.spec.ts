import { expect, test, type Page } from "@playwright/test";
import { openScreen } from "./open";
import { SIGNED_IN_SCREENS } from "./screens";

// E47-S05 (#1319), Gherkin "Help is where it always was" (WCAG 3.2.6): on every shell screen the Help
// entry is in the same place in the top bar, in the same order among its neighbours, and opens the
// cheatsheet. The API is stubbed at the network layer (C-13.5).

interface Slot {
  readonly order: readonly string[];
  readonly row: number;
  readonly right: number;
}

/** The top bar's buttons in DOM order, and where Help sits: its row (top edge) and its distance from the bar's right edge. */
const slot = (page: Page): Promise<Slot> =>
  page.evaluate(() => {
    const bar = document.querySelector("header");
    if (bar === null) throw new Error("no banner");
    const names = [...bar.querySelectorAll("button")].map(
      (b) => (b.textContent ?? "").split(" ")[0] ?? "",
    );
    const help = [...bar.querySelectorAll("button")].find((b) => b.textContent?.startsWith("Help"));
    if (help === undefined) throw new Error("no Help entry in the top bar");
    const box = help.getBoundingClientRect();
    return {
      order: names.map((n) => (n.startsWith("Connection") ? "Connection" : n)),
      row: Math.round(box.top - bar.getBoundingClientRect().top),
      right: Math.round(bar.getBoundingClientRect().right - box.right),
    };
  });

test("Help is in the same slot on every shell screen and opens the cheatsheet", async ({
  page,
}) => {
  const slots: Slot[] = [];
  for (const screen of SIGNED_IN_SCREENS) {
    await openScreen(page, screen);
    slots.push(await slot(page));
    const help = page.getByRole("banner").getByRole("button", { name: /^Help/u });
    await help.click();
    await expect(page.getByRole("dialog", { name: /hotkey|keyboard|shortcut/iu })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(help, `${screen.id}: focus returns to Help`).toBeFocused();
  }
  expect(slots.length).toBeGreaterThan(1);
  const [first, ...rest] = slots;
  for (const s of rest) expect(s).toEqual(first);
  const order = first?.order ?? [];
  expect(order.indexOf("Help")).toBeGreaterThan(order.indexOf("Connection"));
  expect(order.indexOf("Help")).toBeLessThan(order.indexOf("Sign"));
});

test("Ctrl+/ opens the same cheatsheet the Help entry does", async ({ page }) => {
  const [screen] = SIGNED_IN_SCREENS;
  if (screen === undefined) throw new Error("no signed-in screen");
  await openScreen(page, screen);
  await page.keyboard.press("Control+/");
  await expect(page.getByRole("dialog", { name: /hotkey|keyboard|shortcut/iu })).toBeVisible();
});
