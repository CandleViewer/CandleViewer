import { expect, packTest as test } from "../ga/fixtures";
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

test("E09-TC-B06 forced password change succeeds and links back to sign-in @ga-regression @ga-area-primary", async ({
  page,
}) => {
  let body = "";
  await page.route("**/api/v1/auth/password", (r) => {
    body = r.request().postData() ?? "";
    return r.fulfill({ status: 204 });
  });
  await page.goto("/login/change-password");
  await fillChange(page, NEW_PW);
  await expect(page.getByRole("heading", { name: "Password changed" })).toBeVisible();
  expect(JSON.parse(body)).toEqual({ current_password: "pw-old", new_password: NEW_PW });
  await expect(page.getByRole("link", { name: "Continue to sign in" })).toHaveAttribute(
    "href",
    "/login",
  );
});

test("E09-TC-B07 8-character password is refused client-side, no request sent @ga-regression @ga-area-primary", async ({
  page,
}) => {
  let calls = 0;
  await page.route("**/api/v1/auth/password", (r) => {
    calls += 1;
    return r.fulfill({ status: 204 });
  });
  await page.goto("/login/change-password");
  await fillChange(page, "short-pw1");
  await expect(page.getByRole("alert")).toHaveText("Use at least 12 characters.");
  expect(calls).toBe(0);
});

test("E09-TC-B08 breached password refused by the server is surfaced @ga-regression @ga-area-primary", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/password", (r) =>
    r.fulfill(json({ code: "password_breached" }, 422)),
  );
  await page.goto("/login/change-password");
  await fillChange(page, "password123456");
  await expect(page.getByRole("alert")).toHaveText("This password appears in a known breach list.");
});

test("E09-TC-B09 wrong current password is refused and the form stays put @ga-regression @ga-area-primary", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/password", (r) => r.fulfill(json({}, 403)));
  await page.goto("/login/change-password");
  await fillChange(page, NEW_PW);
  await expect(page.getByRole("alert")).toHaveText("That password was not accepted.");
  await expect(page.getByRole("heading", { name: "Choose a new password" })).toBeVisible();
});

test("E09-TC-B06 mismatched confirmation is caught; keyboard submit works @ga-regression @ga-area-primary", async ({
  page,
}) => {
  await page.goto("/login/change-password");
  await page.getByLabel("Current password").focus();
  await page.keyboard.type("pw-old");
  await page.keyboard.press("Tab");
  await page.keyboard.type(NEW_PW);
  await page.getByLabel("Confirm new password").fill("something else entirely");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("Passwords don't match.");
});
