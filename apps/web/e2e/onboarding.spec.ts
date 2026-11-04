import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { stubNoViewAs } from "./support/api";

// E09-S06: first sign-in lands in the terminal and shows the SCR-019 card; axe clean.
const items = ["tailscale", "totp", "sub_account", "api_key", "profile_limits", "demo_session"].map(
  (key) => ({
    key,
    state: "pending",
    reason: null,
    unblock_at: null,
    action_route: "/settings/accounts",
  }),
);

// Network-layer session stubs (same pattern as shell-bootstrap.spec.ts); app code is not mocked.
async function signIn(page: import("@playwright/test").Page): Promise<void> {
  const ok = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      ok({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(ok({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(ok({ bindings: [] })));
  await stubNoViewAs(page); // E42-S03: the fourth boot read
}

test("SCR-019 card renders on first sign-in; axe clean with tour open", async ({ page }) => {
  await signIn(page);
  await page.route("**/api/v1/onboarding/checklist", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ complete: false, dismissed: false, items }),
    }),
  );
  await page.goto("/terminal/last");
  await expect(page.getByRole("heading", { name: "Finish setting up" })).toBeVisible();
  await expect(page.getByRole("dialog")).toBeVisible();
  const res = await new AxeBuilder({ page }).analyze();
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("no tour auto-offer once the checklist is complete", async ({ page }) => {
  await signIn(page);
  await page.route("**/api/v1/onboarding/checklist", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        complete: true,
        dismissed: false,
        items: items.map((i) => ({ ...i, state: "ok" })),
      }),
    }),
  );
  await page.goto("/terminal/last");
  await expect(page.getByText("Setup complete.")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
