import { test, expect } from "@playwright/test";
import { json } from "../support/api";

// E09-Q02 (#293) enrolment.spec. SCR-003 (QR + secret + recovery codes) has no standalone screen
// yet (R-006 is unbuilt); its steps are exercised inside the SCR-017 wizard in onboarding.spec.ts.
// Only the shipped SCR-004 forced password change is covered here.
const NEW_PW = "correct horse battery staple";

async function fillChange(page: import("@playwright/test").Page, next: string, confirm = next) {
  await page.getByLabel("Current password").fill("pw-old");
  await page.getByLabel("New password", { exact: true }).fill(next);
  await page.getByLabel("Confirm new password").fill(confirm);
  await page.getByRole("button", { name: "Change password" }).click();
}

/** `authChangePassword`'s `200`: the rotated session's token bundle (#2110, SR-013). */
const CHANGED = {
  status: "password_changed",
  tokens: {
    access_token: "e2e-rotated",
    token_type: "Bearer",
    expires_in: 720,
    refresh_token: null,
  },
};

test("E09-TC-B06 forced password change succeeds and this device stays signed in", async ({
  page,
}) => {
  let body = "";
  await page.route("**/api/v1/auth/password", (r) => {
    body = r.request().postData() ?? "";
    return r.fulfill(json(CHANGED));
  });
  await page.goto("/login/change-password");
  await fillChange(page, NEW_PW);
  await expect(page.getByRole("heading", { name: "Password changed" })).toBeFocused();
  expect(JSON.parse(body)).toEqual({ current_password: "pw-old", new_password: NEW_PW });
  await expect(
    page.getByText("You've been signed out on your other devices. This device stays signed in."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible();
});

test("E09-TC-B07 a 13-character password is refused client-side, no request sent", async ({
  page,
}) => {
  let calls = 0;
  await page.route("**/api/v1/auth/password", (r) => {
    calls += 1;
    return r.fulfill(json(CHANGED));
  });
  await page.goto("/login/change-password");
  await fillChange(page, "short-pw1-abc");
  const next = page.getByLabel("New password", { exact: true });
  await expect(next).toBeFocused();
  await expect(next).toHaveAccessibleDescription(/^Use at least 14 characters\./);
  expect(calls).toBe(0);
});

test("E09-TC-B08 breached password refused by the server clears both new fields", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/password", (r) =>
    r.fulfill(json({ status: 422, code: "password_breached" }, 422)),
  );
  await page.goto("/login/change-password");
  await fillChange(page, "password123456");
  const next = page.getByLabel("New password", { exact: true });
  await expect(next).toHaveAccessibleDescription(
    /^This password appears in a known breach list\. We cleared both new password fields/,
  );
  await expect(next).toHaveValue("");
  await expect(page.getByLabel("Confirm new password")).toHaveValue("");
});

test("E09-TC-B09 wrong current password is refused and the form stays put", async ({ page }) => {
  await page.route("**/api/v1/auth/password", (r) =>
    r.fulfill(json({ status: 403, code: "current_password_invalid" }, 403)),
  );
  await page.goto("/login/change-password");
  await fillChange(page, NEW_PW);
  const current = page.getByLabel("Current password");
  await expect(current).toBeFocused();
  await expect(current).toHaveAccessibleDescription(/^Your current password is incorrect\./);
  await expect(page.getByRole("heading", { name: "Choose a new password" })).toBeVisible();
});

test("E09-TC-B06 mismatched confirmation is caught; keyboard submit works", async ({ page }) => {
  await page.goto("/login/change-password");
  await page.getByLabel("Current password").fill("pw-old");
  await page.getByLabel("New password", { exact: true }).fill(NEW_PW);
  await page.getByLabel("Confirm new password").fill("something else entirely");
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Confirm new password")).toHaveAccessibleDescription(
    /^Passwords don't match\./,
  );
});
