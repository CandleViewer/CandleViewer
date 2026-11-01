import { test, expect } from "@playwright/test";
import { assertNoClientSecrets, json, watchForLeaks } from "../support/api";
import { OTP_SEED, totp } from "../support/totp";

// E09-Q02 (#293) login.spec. API stubbed at the network layer (C-13.5). SCR-002 (#2711) is a step
// inside R-001: A05, A06, A09 and A10's UI halves are here; the recovery form is built with a switch
// that is off by default, so A11's UI half stays deferred (see qa/plans/e09-q02-automation-status.md).
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

// ---- SCR-002 (#2711): the second-factor step, UI halves ----
const HANDLE = "t-1";
const CODE = "123456";
const MFA = json({ status: "mfa_required", mfa_token: HANDLE, methods: ["totp"], expires_in: 300 });
/** Every refused code is the one `401`, whatever its body (E09-D12 F-2). */
const MFA_REFUSED = (title = "Unauthorized") => json({ title, code: "mfa_invalid" }, 401);
const VERIFY = "**/api/v1/auth/mfa/verify";

async function toTwoFactor(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/login", (r) => r.fulfill(MFA));
  await page.goto("/login");
  await signIn(page);
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeFocused();
  return page.getByRole("textbox", { name: "Two-factor code" });
}

test("E09-TC-A05 (UI half) an invalid code is cleared, marked and focused, and never echoed @electron", async ({
  page,
}) => {
  const bodies: unknown[] = [];
  await page.route(VERIFY, (r) => {
    bodies.push(JSON.parse(r.request().postData() ?? "null"));
    return r.fulfill(MFA_REFUSED());
  });
  const code = await toTwoFactor(page);
  await code.fill(CODE); // a complete code submits once
  await expect(page.getByText("That code isn't valid.")).toBeVisible();
  await expect(code).toHaveValue("");
  await expect(code).toBeFocused();
  await expect(code).toHaveAttribute("aria-invalid", "true");
  expect(bodies).toEqual([{ mfa_token: HANDLE, method: "totp", code: CODE }]);
  expect(await page.content()).not.toContain(HANDLE);
  await assertNoClientSecrets(page, ["pw-a1", HANDLE, CODE]);
});

test("E09-TC-A06 (UI half) a replayed code reads exactly as an invalid one", async ({ page }) => {
  const answers = [MFA_REFUSED("Unauthorized"), MFA_REFUSED("Replayed")];
  await page.route(VERIFY, (r) => r.fulfill(answers.shift() ?? MFA_REFUSED()));
  const code = await toTwoFactor(page);
  const renders: string[] = [];
  for (let i = 0; i < 2; i += 1) {
    await code.fill(CODE);
    await expect(code).toHaveAttribute("aria-invalid", "true");
    await expect(code).toBeFocused();
    renders.push(await page.getByRole("main").innerHTML());
  }
  expect(renders[1]).toBe(renders[0]);
  expect(renders.join("")).not.toMatch(/replay|expired/iu);
});

test("E09-TC-A09 (UI half) five refusals end the challenge: expired, nothing more sent, back to SCR-001", async ({
  page,
}) => {
  let hits = 0;
  await page.route(VERIFY, (r) => {
    hits += 1;
    return r.fulfill(MFA_REFUSED());
  });
  const code = await toTwoFactor(page);
  for (let i = 1; i <= 4; i += 1) {
    await code.fill(CODE);
    await expect(code).toHaveAttribute("aria-invalid", "true");
    expect(hits).toBe(i);
  }
  await code.fill(CODE);
  const back = page.getByRole("button", { name: "Back to login" });
  await expect(back).toBeFocused();
  await expect(page.getByRole("alert")).toHaveText("This code has expired. Please log in again.");
  await expect(page.getByRole("textbox", { name: "Two-factor code" })).toHaveCount(0);
  expect(hits).toBe(5);
  await back.press("Enter");
  await expect(page.getByRole("heading", { name: "Sign in to CandleViewer" })).toBeVisible();
  await expect(page.getByLabel("Username or email")).toBeFocused();
  expect(hits).toBe(5);
});

test("E09-TC-A10 (UI half) past expires_in the step warns, then expires and returns to SCR-001", async ({
  page,
}) => {
  await page.clock.install({ time: Date.UTC(2026, 0, 1, 9, 0, 0) });
  let hits = 0;
  await page.route(VERIFY, (r) => {
    hits += 1;
    return r.fulfill(MFA_REFUSED());
  });
  await toTwoFactor(page);
  await page.clock.runFor(300_000 - 30_000);
  await expect(page.getByRole("main").getByRole("status")).toHaveText(
    "This sign-in step expires in less than 30 seconds.",
  );
  await page.clock.runFor(30_000);
  await expect(page.getByRole("alert")).toHaveText("This code has expired. Please log in again.");
  await expect(page.getByRole("button", { name: "Back to login" })).toBeFocused();
  await page.getByRole("button", { name: "Back to login" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to CandleViewer" })).toBeVisible();
  expect(hits).toBe(0);
});

test("E09-TC-A02 (UI half) the verify 200 hands over by a full page load; no handle, code or token is kept", async ({
  page,
}) => {
  const token = "mk-a1"; // a marker for the bundle's access value, not a credential
  await page.route(VERIFY, (r) =>
    r.fulfill(
      json({
        status: "authenticated",
        tokens: { access_token: token, token_type: "Bearer", expires_in: 600 },
        user: { id: "u-1", username: "ann", email: "a@x.test", roles: ["owner"], status: "active" },
      }),
    ),
  );
  await page.route("**/api/v1/auth/refresh", (r) => r.fulfill(json({ code: "x" }, 401)));
  const code = await toTwoFactor(page);
  const reloaded = page.waitForRequest((r) => new URL(r.url()).pathname === "/api/v1/auth/refresh");
  await code.fill(CODE);
  await reloaded; // the page load re-derives the access token from the refresh cookie (ADR-0020)
  // the stub's refresh is refused, so the new page ends at SCR-001: a fresh page, nothing carried
  await expect(page.getByRole("heading", { name: "Sign in to CandleViewer" })).toBeVisible();
  await assertNoClientSecrets(page, ["pw-a1", HANDLE, CODE, token]);
});

test("E09-TC-A01 a direct load of /login/2fa starts at SCR-001 with no query", async ({ page }) => {
  await page.goto("/login/2fa?mfa_token=planted");
  await expect(page.getByRole("heading", { name: "Sign in to CandleViewer" })).toBeVisible();
  await expect(page).toHaveURL(/\/login$/u);
});

// Every failed sign-in, whatever the account's state, is the contract's one 401 (SR-014, #4961).
const REFUSED = json({ code: "unauthenticated" }, 401);

test("E09-TC-A03 disabled account is refused with no session @electron", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (r) => r.fulfill(REFUSED));
  await page.goto("/login");
  await signIn(page);
  await expect(page.getByRole("alert")).toHaveText(
    "Couldn't sign you in. Check your details and try again.",
  );
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
    await expect(page.getByRole("alert")).toHaveText(
      "Couldn't sign you in. Check your details and try again.",
    );
    messages.push(id);
  }
  expect(messages).toHaveLength(2);
});

test("E09-TC-A08 (UI half) a locked account reads as the one failure string", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (r) => r.fulfill(REFUSED));
  await page.goto("/login");
  await signIn(page);
  await expect(page.getByRole("alert")).toHaveText(
    "Couldn't sign you in. Check your details and try again.",
  );
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
