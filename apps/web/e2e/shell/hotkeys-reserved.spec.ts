import { stubSession } from "../support/api";
import { expect, test } from "../ga/fixtures";

// E10-Q02 hotkeys (plan step HK-1; BQ-04, re-read at #5214's merge): what this build ships. Ctrl+K
// is reserved for the command palette, which is not in this build: the dispatcher takes the key
// (default prevented) and opens nothing. Ctrl+/ opens the cheatsheet, now a modal dialog (D-03).
// Opening and running the palette is the "SCR-012 command palette, #5236" row of the plan's §3.
// Rebind -> conflict -> swap -> reload is hotkeys.spec.ts (E49-S07).

test("@plan-HK-1 Ctrl+K is taken by the shell and opens nothing; Ctrl+/ opens the cheatsheet @ga-regression @ga-area-shell @story-US-SET-002", async ({
  page,
}) => {
  await stubSession(page, { role: "viewer" });
  await page.goto("/terminal");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.evaluate(() => {
    const w = globalThis as unknown as {
      cvKeys: string[];
      addEventListener: (t: "keydown", l: (e: KeyboardEvent) => void) => void;
    };
    w.cvKeys = [];
    w.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.key !== "Control") w.cvKeys.push(`${e.key}:${String(e.defaultPrevented)}`);
    });
  });
  const keys = () => page.evaluate(() => (globalThis as unknown as { cvKeys: string[] }).cvKeys);
  await page.keyboard.press("Control+k");
  await expect.poll(keys).toEqual(["k:true"]);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.keyboard.press("Control+/");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
});
