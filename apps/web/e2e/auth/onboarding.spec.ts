import { test, expect, type Locator, type Page } from "@playwright/test";
import { json, stubSession } from "../support/api";
import { OTP_SEED, totp } from "../support/totp";

// E09-Q02 (#293) onboarding.spec: SCR-017 invite wizard (embeds password + TOTP steps) and the
// SCR-019 checklist card. Network stubbed; no UI invented.
const INVITE_ID = "inv-q02";

test("E09-TC-E02/E03 invite wizard: accept, password, TOTP, recovery codes shown once", async ({
  page,
}) => {
  const T = Date.UTC(2026, 0, 1);
  let confirmBody = "";
  await page.route(`**/api/v1/invites/${INVITE_ID}`, (r) =>
    r.request().method() === "GET"
      ? r.fulfill(json({ display_name: "Ann", role: "viewer", expires_at: "2026-02-01T00:00:00Z" }))
      : r.fulfill(
          json({
            method_id: "m1",
            otpauth_uri: "otpauth://x",
            secret_base32: OTP_SEED,
          }),
        ),
  );
  await page.route(`**/api/v1/invites/${INVITE_ID}/confirm`, (r) => {
    confirmBody = r.request().postData() ?? "";
    return r.fulfill(json({ status: "active", role: "viewer", recovery_codes: ["rc-1", "rc-2"] }));
  });
  await page.goto(`/invite/${INVITE_ID}`);
  await expect(page.getByRole("heading", { name: "Welcome, Ann" })).toBeVisible();
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByLabel("New password").fill("correct horse battery");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText(OTP_SEED)).toBeVisible();
  const code = totp(OTP_SEED, T);
  await page.getByLabel("Authenticator code").fill(code);
  await page.getByRole("button", { name: "Activate account" }).click();
  await expect(page.getByText(/Step 4 of 4/)).toBeVisible();
  await expect(page.getByText("rc-1")).toBeVisible();
  expect(confirmBody).toContain(code);
  // Role stays viewer: no elevation during onboarding (SR-027).
  await expect(page.getByText(/viewer/i).first()).toBeVisible();
});

test("E09-TC-E04 reused or expired invite shows one uniform message", async ({ page }) => {
  await page.route("**/api/v1/invites/**", (r) => r.fulfill(json({ detail: "x" }, 404)));
  const seen: string[] = [];
  for (const tok of ["inv-expired", "inv-reused"]) {
    await page.goto(`/invite/${tok}`);
    await expect(page.getByRole("heading", { name: "Invitation not valid" })).toBeVisible();
    seen.push((await page.getByRole("heading", { level: 1 }).innerText()).trim());
  }
  expect(seen[0]).toBe(seen[1]);
});

test("E09-TC-E03 wrong TOTP code in the wizard shows an inline error and stays on step 3", async ({
  page,
}) => {
  await page.route(`**/api/v1/invites/${INVITE_ID}`, (r) =>
    r.request().method() === "GET"
      ? r.fulfill(json({ display_name: "Ann", role: "viewer", expires_at: "x" }))
      : r.fulfill(json({ method_id: "m1", otpauth_uri: "otpauth://x", secret_base32: "AAAA" })),
  );
  await page.route(`**/api/v1/invites/${INVITE_ID}/confirm`, (r) => r.fulfill(json({}, 422)));
  await page.goto(`/invite/${INVITE_ID}`);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByLabel("New password").fill("correct horse battery");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Authenticator code").fill("000000");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("That code did not work. Try again.");
});

const items = ["tailscale", "totp", "sub_account", "api_key", "profile_limits", "demo_session"].map(
  (key) => ({ key, state: "pending", reason: null, unblock_at: null, action_route: "/settings" }),
);

test("E09-TC-E05 skip persists: dismissed checklist stays hidden after reload", async ({
  page,
}) => {
  await stubSession(page, { role: "viewer" });
  let dismissed = false;
  await page.route("**/api/v1/onboarding/checklist", (r) =>
    r.fulfill(
      json({ complete: true, dismissed, items: items.map((i) => ({ ...i, state: "ok" })) }),
    ),
  );
  await page.route("**/api/v1/onboarding/checklist/dismiss", (r) => {
    dismissed = true;
    return r.fulfill(json({}));
  });
  await page.goto("/terminal/last");
  await page.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByText("Setup complete.")).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("Setup complete.")).toHaveCount(0);
});

/**
 * Presses Tab, at most three times, until `target` holds focus. E09-D12 9.2 and E09-D05 9.1 want a step change to
 * focus the step's first control (#291 owns that); today each phase unmounts the control that had focus, so the next
 * Tab reaches it. The path stays on the keyboard and passes whether or not the step manages focus.
 */
async function tabTo(page: Page, target: Locator): Promise<void> {
  for (let presses = 0; presses < 3; presses += 1) {
    if (await target.evaluate((el) => el === el.ownerDocument.activeElement)) break;
    await page.keyboard.press("Tab");
  }
  await expect(target).toBeFocused();
}

test("E09-TC-E03 keyboard-only: the whole wizard is reachable and submittable with Tab, Space and Enter", async ({
  page,
}) => {
  await page.route(`**/api/v1/invites/${INVITE_ID}`, (r) =>
    r.request().method() === "GET"
      ? r.fulfill(json({ display_name: "Ann", role: "viewer", expires_at: "2026-02-01T00:00:00Z" }))
      : r.fulfill(json({ method_id: "m1", otpauth_uri: "otpauth://x", secret_base32: OTP_SEED })),
  );
  const confirms: unknown[] = [];
  await page.route(`**/api/v1/invites/${INVITE_ID}/confirm`, (r) => {
    confirms.push(r.request().postDataJSON());
    return r.fulfill(json({ status: "active", role: "viewer", recovery_codes: ["rc-1", "rc-2"] }));
  });
  await page.goto(`/invite/${INVITE_ID}`);
  await expect(page.getByRole("heading", { name: "Welcome, Ann" })).toBeVisible();
  await tabTo(page, page.getByRole("button", { name: "Accept invitation" }));
  await page.keyboard.press("Space");
  await expect(page.getByRole("heading", { name: "Choose a password" })).toBeVisible();
  await tabTo(page, page.getByLabel("New password"));
  await page.keyboard.type("correct horse battery");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Set up your authenticator" })).toBeVisible();
  await tabTo(page, page.getByLabel("Authenticator code"));
  const code = totp(OTP_SEED, Date.UTC(2026, 0, 1));
  await page.keyboard.type(code);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Activate account" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "You are set up" })).toBeVisible();
  await tabTo(page, page.getByRole("link", { name: "Go to sign in" }));
  expect(confirms).toEqual([{ method_id: "m1", code }]);
});
