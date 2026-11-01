import { test, expect, type Page } from "@playwright/test";

// E49-S07 e2e. Session stubs are network-layer (same pattern as onboarding.spec.ts); app code is
// not mocked, so /settings/hotkeys passes the real auth guard and every conflict class runs.
// An Owner with `settings:write`: the profile and the audit outbox are keyed by `/me`'s user id,
// and the audit is POSTed only for a session holding that permission (#305, A55).
const USER_ID = "00000000-0000-4000-8000-000000000305";
const OUTBOX = `cv.hotkey-audit-outbox.v1:${USER_ID}`;
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
          id: USER_ID,
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
}

/**
 * A command's row, by its exact row header: a row is named from its content, so after a swap the message
 * "Price zoom in: -; Price zoom out: +" would put another command's label in that row's name (CR-305BD-01).
 */
const rowOf = (page: Page, label: string) =>
  page.locator("tr", { has: page.getByRole("rowheader", { name: label, exact: true }) });

async function bind(page: Page, label: string, key: string, mods: string[] = []): Promise<void> {
  for (const m of mods) await page.getByLabel(`${m} for ${label}`, { exact: true }).check();
  await page.getByLabel(`Key for ${label}`, { exact: true }).fill(key);
  await rowOf(page, label)
    .getByRole("button", { name: `Save ${label}`, exact: true })
    .click();
}

/** SCR-113's message line: no live region of its own, the shell announcer speaks it (#305). */
const message = (page: Page) => page.locator("#hk-msg");
const keyOf = (page: Page, label: string) => rowOf(page, label).locator("kbd");

test.describe("SCR-113 conflict classes", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
    await page.goto("/settings/hotkeys");
    await expect(page.getByRole("heading", { name: "Hotkeys" })).toBeVisible();
  });

  test("same-context conflict is refused with the owner named", async ({ page }) => {
    await bind(page, "Price zoom in", "C");
    await expect(message(page)).toContainText("already bound to");
  });

  test("reserved browser/OS key is refused", async ({ page }) => {
    await bind(page, "Price zoom in", "W", ["Ctrl"]);
    await expect(message(page)).toContainText("reserved by");
  });

  test("bare key on a destructive command needs explicit acknowledgement and is audited", async ({
    page,
  }) => {
    const audits: unknown[] = [];
    await page.route("**/api/v1/settings/hotkey-audit", (r) => {
      audits.push(r.request().postDataJSON());
      return r.fulfill({ status: 204 });
    });
    // A letter is refused outright on a dangerous command (BQ-3, AC5): the acknowledged path is a bare non-letter.
    await bind(page, "Cancel all working orders for symbol", "Del");
    await expect(message(page)).toContainText("destructive");
    await page.getByRole("button", { name: "I understand, bind anyway" }).click();
    await expect.poll(() => audits.length).toBe(1);
    expect(audits[0]).toMatchObject({ command_id: "dom.cancel_all", after: "Del" });
  });

  test("audit survives a failed POST and is re-sent after reload", async ({ page }) => {
    await page.route("**/api/v1/settings/hotkey-audit", (r) => r.fulfill({ status: 503 }));
    await bind(page, "Cancel all working orders for symbol", "Del");
    await page.getByRole("button", { name: "I understand, bind anyway" }).click();
    await expect
      .poll(() => page.evaluate((key) => localStorage.getItem(key), OUTBOX))
      .toContain("dom.cancel_all");
    await page.unroute("**/api/v1/settings/hotkey-audit");
    const sent = page.waitForRequest("**/api/v1/settings/hotkey-audit");
    await page.route("**/api/v1/settings/hotkey-audit", (r) => r.fulfill({ status: 204 }));
    await page.reload();
    expect((await sent).postDataJSON()).toMatchObject({ command_id: "dom.cancel_all" });
    await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), OUTBOX)).toBe("[]");
  });

  test("import rejects conflicting and reserved entries in a report", async ({ page }) => {
    const box = page.getByLabel("Import keymap (JSON)");
    await box.fill(JSON.stringify({ "dom.zoom_in": "C", "dom.zoom_out": "Ctrl+W" }));
    await page.getByRole("button", { name: "Import" }).click(); // #305: applied on Import, never on blur
    const report = page.getByRole("list", { name: "Import report" });
    await expect(report).toContainText("dom.zoom_in");
    await expect(report).toContainText("dom.zoom_out");
  });

  test("rebind, conflict, one-click swap, and the swap survives a reload (AC3)", async ({
    page,
  }) => {
    await bind(page, "Price zoom in", "-");
    await expect(message(page)).toContainText('already bound to "Price zoom out"');
    // The keyboard path (A11Y-305B-01): Swap is the next stop after the row's Save.
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Swap" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(keyOf(page, "Price zoom in")).toHaveText("-");
    await expect(keyOf(page, "Price zoom out")).toHaveText("+");
    await page.reload();
    await expect(keyOf(page, "Price zoom in")).toHaveText("-");
    await expect(keyOf(page, "Price zoom out")).toHaveText("+");
  });

  test("export, reset and import round-trip every binding (AC7)", async ({ page }) => {
    await bind(page, "Price zoom in", "J");
    await page.getByRole("button", { name: "Export" }).click();
    const exported = await page.getByLabel("Export keymap (JSON)").inputValue();
    await page.getByRole("button", { name: "Reset all" }).click();
    await expect(keyOf(page, "Price zoom in")).toHaveText("+");
    const box = page.getByLabel("Import keymap (JSON)");
    await box.fill(exported);
    await page.getByRole("button", { name: "Import" }).click();
    await expect(keyOf(page, "Price zoom in")).toHaveText("J");
    await expect(page.getByRole("list", { name: "Import report" })).toHaveCount(0);
  });
});

test("Ctrl+/ opens the cheatsheet with a Customise link", async ({ page }) => {
  await signIn(page);
  await page.goto("/terminal/last");
  await expect(page.getByRole("main")).toBeVisible();
  await page.keyboard.press("Control+/");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Customise" })).toHaveAttribute(
    "href",
    "/settings/hotkeys",
  );
});

test("inert press of an unregistered destructive binding explains once, politely, with context", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/terminal/last");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByTestId("toast-host")).toBeAttached();
  for (let i = 0; i < 3; i++) await page.keyboard.press("Control+Shift+X");
  const host = page.getByRole("region", { name: "Notifications" });
  await expect(host.getByRole("group")).toHaveCount(1);
  await expect(host).toContainText(
    "Cancel all working orders for symbol is not available here (DOM view)",
  );
  await expect(host).toContainText("needs working orders exist");
});

test("inert press of a context-gated command (drawing selected) explains what it needs", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/terminal/last");
  await expect(page.getByRole("main")).toBeVisible();
  // The window listener mounts after the route paints: press until it hears one (the toast region exists only then).
  await expect(async () => {
    await page.keyboard.press("Delete");
    await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
      "needs drawing selected",
      { timeout: 500 },
    );
  }).toPass({ timeout: 10_000 });
});

test("the key field keeps its name, 'Key for <command>', once a value is typed", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/settings/hotkeys");
  await page.getByRole("textbox", { name: "Key for Price zoom in", exact: true }).fill("J");
  await expect(
    page.getByRole("textbox", { name: "Key for Price zoom in", exact: true }),
  ).toHaveValue("J");
});

test("a rebind persists across reload", async ({ page }) => {
  await signIn(page);
  await page.goto("/settings/hotkeys");
  await bind(page, "Price zoom in", "J");
  await page.reload();
  await expect(keyOf(page, "Price zoom in")).toHaveText("J");
});
