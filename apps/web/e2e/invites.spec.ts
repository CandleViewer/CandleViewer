import { type Page } from "@playwright/test";
import { expect, packTest as test } from "./ga/fixtures";
import AxeBuilder from "@axe-core/playwright";

// E09-S05 (PR #1689 review): wizard -> done, expired and reused links, axe on SCR-017.
// SCR-123 sits behind the owner guard, which the shell does not bootstrap yet (E10);
// its create path and axe run in test/features/invites.test.tsx. The API is mocked at the network layer.

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

async function seriousViolations(page: Page): Promise<unknown[]> {
  const res = await new AxeBuilder({ page }).analyze();
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

test("SCR-017 four-step wizard completes; axe clean @ga-regression @ga-area-primary @story-US-ONB-006", async ({
  page,
}) => {
  await page.route("**/api/v1/invites/tok-e2e-0123456789", (r) =>
    r.request().method() === "GET"
      ? r.fulfill(json({ display_name: "Ann", role: "viewer", expires_at: "x" }))
      : r.fulfill(json({ method_id: "m1", otpauth_uri: "otpauth://x", secret_base32: "AAAA" })),
  );
  await page.route("**/api/v1/invites/tok-e2e-0123456789/confirm", (r) =>
    r.fulfill(json({ status: "active", role: "viewer", recovery_codes: ["rc-1"] })),
  );
  await page.goto("/invite/tok-e2e-0123456789");
  await expect(page.getByText(/Step 1 of 4/)).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByLabel("New password").fill("correct horse battery");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Authenticator code").fill("123456");
  await page.getByRole("button", { name: "Activate account" }).click();
  await expect(page.getByText(/Step 4 of 4/)).toBeVisible();
  await expect(page.getByText("rc-1")).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("expired and reused links show the same uniform message @ga-regression @ga-area-primary @story-US-ONB-006", async ({
  page,
}) => {
  await page.route("**/api/v1/invites/**", (r) => r.fulfill(json({ detail: "x" }, 404)));
  for (const tok of ["tok-expired-0123456789", "tok-reused-0123456789"]) {
    await page.goto(`/invite/${tok}`);
    await expect(page.getByRole("heading", { name: "Invitation not valid" })).toBeVisible();
    await expect(
      page.getByText("This invitation is no longer valid. Ask the owner for a new one."),
    ).toBeVisible();
  }
});
