import { test, expect } from "@playwright/test";
import { assertNoClientSecrets, json, watchForLeaks } from "../support/api";
import { OTP_SEED, totp } from "../support/totp";

// E09-Q02 (#293) login.spec. API stubbed at the network layer (C-13.5); SCR-002 UI is not built
// yet, so the TOTP/recovery cases are deferred (see qa/plans/e09-q02-automation-status.md).
// Tests tagged @electron also run in the Electron shell lane.

async function signIn(page: import("@playwright/test").Page): Promise<void> {
  await page.getByLabel("Username or email").fill("ann");
  await page.getByLabel("Password", { exact: true }).fill("pw-a1");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("E09-TC-A01 password step returns mfa_required and shows the second-factor step @electron", async ({
  page,
}) => {
  const guard = watchForLeaks(page, ["pw-a1"]);
  let body = "";
  await page.route("**/api/v1/auth/login", (r) => {
    body = r.request().postData() ?? "";
    return r.fulfill(json({ status: "mfa_required", mfa_token: "t-1", methods: ["totp"] }));
  });
  await page.goto("/login");
  await signIn(page);
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeVisible();
  expect(JSON.parse(body)).toEqual({ identifier: "ann", password: "pw-a1" });
  // No session cookie before MFA completes.
  expect(await page.context().cookies()).toEqual([]);
  await assertNoClientSecrets(page, ["pw-a1", "t-1"]);
  await guard.flush();
});

// Every failed sign-in, whatever the account's state, is the contract's one 401 (SR-014, #4961).
const REFUSED = json({ code: "unauthenticated" }, 401);

test("E09-TC-A03 disabled account is refused with no session @electron", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (r) => r.fulfill(REFUSED));
  await page.goto("/login");
  await signIn(page);
  await expect(page.getByRole("alert")).toHaveText("Username or password is incorrect");
  expect(await page.context().cookies()).toEqual([]);
});

test("E09-TC-A07 unknown user and wrong password are indistinguishable in the UI", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/login", (r) => r.fulfill(json({ detail: "x" }, 401)));
  await page.goto("/login");
  const messages: string[] = [];
  for (const id of ["nobody@example.test", "ann"]) {
    await page.getByLabel("Username or email").fill(id);
    await page.getByLabel("Password", { exact: true }).fill("pw-bad");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).not.toBeEmpty();
    await expect(page.getByRole("alert")).toHaveText("Username or password is incorrect");
    messages.push(id);
  }
  expect(messages).toHaveLength(2);
});

test("E09-TC-A08 (UI half) a locked account reads as the one failure string", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (r) => r.fulfill(REFUSED));
  await page.goto("/login");
  await signIn(page);
  await expect(page.getByRole("alert")).toHaveText("Username or password is incorrect");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
});

test("E09-TC-A01 keyboard-only: tab order SCR-001 and Enter submits @electron", async ({
  page,
}) => {
  let hit = 0;
  await page.route("**/api/v1/auth/login", (r) => {
    hit += 1;
    return r.fulfill(json({}, 401));
  });
  await page.goto("/login");
  await page.getByLabel("Username or email").focus();
  await page.keyboard.type("ann");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password", { exact: true })).toBeFocused();
  await page.keyboard.type("pw-a1");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Show password" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toBeFocused();
  expect(hit).toBe(1);
});

test("E09-TC-A04/A05 TOTP helper: RFC 6238 vector and ±1 step skew window", () => {
  // RFC 6238 App. B, SHA-1, public ASCII seed, T=59 s -> 94287082 (8 digits).
  expect(totp(OTP_SEED, 59_000)).toBe("287082");
  const now = Date.UTC(2026, 0, 1, 0, 0, 10);
  const same = totp(OTP_SEED, now);
  expect(totp(OTP_SEED, now, 1)).not.toBe(same);
  expect(totp(OTP_SEED, now + 30_000)).toBe(totp(OTP_SEED, now, 1));
  expect(same).toMatch(/^\d{6}$/u);
});
