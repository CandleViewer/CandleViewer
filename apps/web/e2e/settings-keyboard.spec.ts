import { test, expect, type Locator, type Page } from "@playwright/test";

// E47-S08 slice 7 (US-SET-001 "Settings are fully operable from the keyboard"): the settings band with the
// keyboard only. Nothing here clicks; every move is Tab, an arrow, Enter, Space, or Esc. Session and settings
// answers are network-layer stubs, as in hotkeys.spec.ts.
async function signIn(page: Page): Promise<void> {
  const ok = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      ok({
        role: "owner",
        permissions: ["settings:read", "settings:write"],
        user: {
          id: "00000000-0000-4000-8000-000000000108",
          email: "owner@example.test",
          username: "owner",
          roles: ["owner"],
          status: "active",
        },
        accounts: [],
        session: { environment: "demo", elevated_until: null },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(ok({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(ok({ bindings: [] })));
  await page.route("**/api/v1/settings", (r) => r.fulfill(ok({})));
}

/** Presses Tab until `target` has focus; fails if it is not reached in `max` presses (a trap or a missing stop). */
async function tabTo(page: Page, target: Locator, max = 40): Promise<void> {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((el) => el === document.activeElement)) return;
  }
  throw new Error(`not reachable with Tab in ${max} presses`);
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
  await page.goto("/settings/appearance");
  await expect(page.getByRole("heading", { name: "Appearance", level: 1 })).toBeVisible();
});

test("the nav is one Tab stop; arrows, Home, End and Enter work it", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "Settings" });
  const open = nav.getByRole("link", { name: "Appearance" });
  await expect(open).toHaveAttribute("aria-current", "page");
  await tabTo(page, open);
  await page.keyboard.press("End");
  const help = nav.getByRole("button", { name: "Help & about" });
  await expect(help).toBeFocused();
  await expect(help).toHaveAccessibleDescription(/not available yet/iu);
  await page.keyboard.press("Home");
  await expect(nav.getByRole("link", { name: "Profile" })).toBeFocused();
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowDown"); // Security, Appearance, Hotkeys
  await expect(nav.getByRole("link", { name: "Hotkeys" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/settings\/hotkeys$/u);
  await expect(page.getByRole("heading", { name: "Hotkeys" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Hotkeys" })).toHaveAttribute("aria-current", "page");
});

test("search says the count and each section path, and Esc returns the page", async ({ page }) => {
  const search = page.getByRole("searchbox", { name: "Search settings" });
  await tabTo(page, search);
  await page.keyboard.type("motion");
  const results = page.getByRole("region", { name: /search results/iu });
  await expect(results.getByText("Settings > Accessibility > Reduced motion")).toBeVisible();
  // One debounced sentence in the shell announcer, with the count and the paths.
  await expect(
    page.getByText(/^2 results: Accessibility; Accessibility > Reduced motion\.$/u),
  ).toBeAttached();
  await page.keyboard.press("Escape");
  await expect(search).toHaveValue("");
  await expect(page.getByRole("heading", { name: "Appearance", level: 1 })).toBeVisible();
});

test("appearance controls state their scope and work with arrows and Space", async ({ page }) => {
  const palette = page.getByRole("group", { name: "Chart palette" });
  await expect(palette).toHaveAccessibleDescription(/Scope: /u);
  const cvd = page.getByRole("radio", { name: /colour-blind safe/iu });
  await tabTo(page, page.getByRole("radio", { name: /default \(green/iu }));
  await page.keyboard.press("ArrowDown");
  await expect(cvd).toBeFocused();
  await expect(cvd).toBeChecked();
  const invert = page.getByRole("checkbox", { name: /invert buy\/sell/iu });
  await tabTo(page, invert);
  await page.keyboard.press("Space");
  await expect(invert).toBeChecked();
  await expect(invert).toHaveAccessibleDescription(/Scope: /u);
});

test("the Accessibility section opens by keyboard and takes focus", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "Settings" });
  await tabTo(page, nav.getByRole("link", { name: "Appearance" }));
  for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowDown"); // Hotkeys .. Data & performance, Accessibility
  await expect(nav.getByRole("link", { name: "Accessibility" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#accessibility$/u);
  await expect(nav.getByRole("link", { name: "Accessibility" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("heading", { name: "Accessibility", level: 2 })).toBeFocused();
});
