import { test, expect, type Page } from "@playwright/test";

// E49-S07 e2e. Session stubs are network-layer (same pattern as onboarding.spec.ts); app code is
// not mocked, so /settings/hotkeys passes the real auth guard and every conflict class runs.
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
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(ok({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(ok({ bindings: [] })));
}

async function bind(page: Page, label: string, key: string, mods: string[] = []): Promise<void> {
  for (const m of mods) await page.getByLabel(`${m} for ${label}`, { exact: true }).check();
  await page.getByLabel(`Key for ${label}`, { exact: true }).fill(key);
  await page
    .getByRole("row", { name: new RegExp(label) })
    .getByRole("button", { name: "Save" })
    .click();
}

test.describe("SCR-113 conflict classes", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
    await page.goto("/settings/hotkeys");
    await expect(page.getByRole("heading", { name: "Hotkeys" })).toBeVisible();
  });

  test("same-context conflict is refused with the owner named", async ({ page }) => {
    await bind(page, "Price zoom in", "C");
    await expect(page.getByRole("alert")).toContainText("already bound to");
  });

  test("reserved browser/OS key is refused", async ({ page }) => {
    await bind(page, "Price zoom in", "W", ["Ctrl"]);
    await expect(page.getByRole("alert")).toContainText("reserved by");
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
    await expect(page.getByRole("alert")).toContainText("destructive");
    await page.getByRole("button", { name: "I understand, bind anyway" }).click();
    await expect.poll(() => audits.length).toBe(1);
    expect(audits[0]).toMatchObject({ command_id: "dom.cancel_all", after: "Del" });
  });

  test("audit survives a failed POST and is re-sent after reload", async ({ page }) => {
    await page.route("**/api/v1/settings/hotkey-audit", (r) => r.fulfill({ status: 503 }));
    await bind(page, "Cancel all working orders for symbol", "Del");
    await page.getByRole("button", { name: "I understand, bind anyway" }).click();
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem("cv.hotkey-audit-outbox.v1")))
      .toContain("dom.cancel_all");
    await page.unroute("**/api/v1/settings/hotkey-audit");
    const sent = page.waitForRequest("**/api/v1/settings/hotkey-audit");
    await page.route("**/api/v1/settings/hotkey-audit", (r) => r.fulfill({ status: 204 }));
    await page.reload();
    expect((await sent).postDataJSON()).toMatchObject({ command_id: "dom.cancel_all" });
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem("cv.hotkey-audit-outbox.v1")))
      .toBe("[]");
  });

  test("import rejects conflicting and reserved entries in a report", async ({ page }) => {
    const box = page.getByLabel("Import keymap JSON");
    await box.fill(JSON.stringify({ "dom.zoom_in": "C", "dom.zoom_out": "Ctrl+W" }));
    await box.blur();
    const report = page.getByRole("list", { name: "Import report" });
    await expect(report).toContainText("dom.zoom_in");
    await expect(report).toContainText("dom.zoom_out");
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
  const host = page.getByTestId("toast-host");
  await expect(host).toHaveAttribute("role", "status");
  await expect(host.locator("p")).toHaveCount(1);
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
  await page.keyboard.press("Delete");
  await expect(page.getByTestId("toast-host")).toContainText("needs drawing selected");
});

test("a rebind persists across reload", async ({ page }) => {
  await signIn(page);
  await page.goto("/settings/hotkeys");
  await bind(page, "Price zoom in", "J");
  await page.reload();
  await expect(page.getByRole("row", { name: /Price zoom in/ }).locator("kbd")).toHaveText("J");
});
