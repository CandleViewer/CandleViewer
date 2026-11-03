import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { json, stubSession } from "./support/api";
import { AXE_GATE_TAGS } from "./a11y/tags";

// E10-S05 (#5236): SCR-012, the command palette, end to end; the palette half of E10-Q02's "Hotkeys & palette"
// scope. The API is stubbed at the network layer (C-13.5); the app code is not mocked.

type Role = "owner" | "manager" | "viewer";

/** A signed-in shell at `path`; `/me` carries `permissions` (the shared stub's are empty). */
async function shellAt(page: Page, path: string, role: Role, permissions: string[] = []) {
  await stubSession(page, { role });
  // Registered last, so it answers first: `/me` with the claims this case needs.
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      json({
        role,
        permissions,
        user: { id: "u-e2e", username: "ann", email: "ann@example.test", roles: [role] },
        session: { environment: "demo", elevated_until: null },
      }),
    ),
  );
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // `/me` has answered (the name and role show): the keymap profile has loaded for this user.
  await expect(page.getByRole("banner").getByText(/^ann · /u)).toBeVisible();
}

const palette = (page: Page) => page.getByRole("dialog", { name: "Command palette" });
const input = (page: Page) => page.getByRole("combobox", { name: "Search commands" });
const trigger = (page: Page) => page.getByRole("button", { name: "Search commands Ctrl+K" });

test("Ctrl+K, type, Enter navigates; the palette closes first", async ({ page }) => {
  await shellAt(page, "/journal", "owner");
  await page.keyboard.press("Control+k");
  await expect(palette(page)).toBeVisible();
  await expect(input(page)).toBeFocused();
  await input(page).fill("alerts");
  await expect(page.getByRole("option").first()).toHaveAccessibleName("Alerts");
  await page.keyboard.press("Enter");
  await expect(palette(page)).toHaveCount(0);
  await expect(page).toHaveURL(/\/alerts$/u);
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
});

test("the trigger opens it, and Esc returns focus to the trigger", async ({ page }) => {
  await shellAt(page, "/journal", "viewer");
  await expect(trigger(page)).toHaveAttribute("aria-keyshortcuts", "Control+K");
  await trigger(page).click();
  await expect(input(page)).toBeFocused();
  const results = await new AxeBuilder({ page }).withTags([...AXE_GATE_TAGS]).analyze();
  expect(results.violations.filter((v) => /serious|critical/u.test(v.impact ?? ""))).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(palette(page)).toHaveCount(0);
  await expect(trigger(page)).toBeFocused();
});

test("keyboard only: run the Hotkey cheatsheet from the palette", async ({ page }) => {
  await shellAt(page, "/journal", "viewer");
  await page.keyboard.press("Control+k");
  await page.keyboard.type("cheatsheet");
  await page.keyboard.press("Enter");
  await expect(palette(page)).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
});

test("a manager without admin:read: no /admin/* row, and /admin/users still 404s", async ({
  page,
}) => {
  await shellAt(page, "/journal", "manager");
  await page.keyboard.press("Control+k");
  for (const word of ["users", "admin"]) {
    await input(page).fill(word);
    await expect(page.getByRole("option")).toHaveCount(0);
    await expect(
      palette(page).getByText(`No command matches “${word}”.`, { exact: false }),
    ).toBeVisible();
  }
  await page.keyboard.press("Escape");
  await page.goto("/admin/users");
  await expect(page).toHaveTitle(/^Not found/u);
});

test("an owner with admin:read reaches Profile and security and Invite user by name (2.4.5)", async ({
  page,
}) => {
  await shellAt(page, "/journal", "owner", ["admin:read"]);
  await page.keyboard.press("Control+k");
  await input(page).fill("profile and security");
  await expect(page.getByRole("option").first()).toHaveAccessibleName("Profile and security");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/settings\/profile$/u); // SCR-112
  await page.keyboard.press("Control+k");
  await input(page).fill("invite user");
  await expect(page.getByRole("option").first()).toHaveAccessibleName("Invite user");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/admin\/users\/new$/u); // SCR-123
});

test("the reduced-motion override makes open and close instant", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await shellAt(page, "/journal", "viewer");
  await page.keyboard.press("Control+k");
  const scrim = page.locator(".cv-dialog__scrim");
  await expect(scrim).toBeVisible();
  const seconds = await scrim.evaluate((node) =>
    getComputedStyle(node)
      .transitionDuration.split(",")
      .map((t) => (t.trim().endsWith("ms") ? parseFloat(t) / 1000 : parseFloat(t))),
  );
  expect(Math.max(...seconds)).toBeLessThanOrEqual(0.001);
  await page.keyboard.press("Escape");
  // No exit fade: the layer is gone within a few frames, well inside the 100 ms motion.duration.fast fade
  // that runs with motion allowed (E10-D04 T-11).
  const frames = await page.evaluate(
    () =>
      new Promise<number>((done) => {
        const tick = (n: number): void => {
          if (document.querySelectorAll(".cv-dialog__scrim").length === 0 || n >= 6) done(n);
          else requestAnimationFrame(() => tick(n + 1));
        };
        tick(0);
      }),
  );
  expect(frames).toBeLessThanOrEqual(3);
  await expect(trigger(page)).toHaveCount(1);
});
