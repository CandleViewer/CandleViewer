import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// E09-S01 (#1605): SCR-001's states + SCR-004. API mocked at the network layer.

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => ({
  status,
  contentType: "application/json",
  headers,
  body: JSON.stringify(body),
});

async function serious(page: Page): Promise<unknown[]> {
  const res = await new AxeBuilder({ page }).analyze();
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

async function fill(page: Page): Promise<void> {
  await page.getByLabel("Username or email").fill("ann");
  await page.getByLabel("Password", { exact: true }).fill("pw");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("idle: axe clean, keyboard reachable", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await serious(page)).toEqual([]);
  await page.getByLabel("Username or email").focus();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password", { exact: true })).toBeFocused();
});

test("invalid: uniform message, focus on alert, axe clean", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (r) => r.fulfill(json({}, 401)));
  await page.goto("/login");
  await fill(page);
  await expect(page.getByRole("alert")).toHaveText(
    "Couldn't sign you in. Check your details and try again.",
  );
  await expect(page.getByRole("alert")).toBeFocused();
  expect(await serious(page)).toEqual([]);
});

test("submitting: fields read-only and submit inert while the request is pending", async ({
  page,
}) => {
  let release: () => void = () => undefined;
  let posts = 0;
  const gate = new Promise<void>((r) => (release = r));
  await page.route("**/api/v1/auth/login", async (r) => {
    posts += 1;
    await gate;
    await r.fulfill(json({}, 401));
  });
  await page.goto("/login");
  await fill(page);
  const password = page.getByLabel("Password", { exact: true });
  await expect(password).toHaveAttribute("readonly", "");
  await expect(password).toBeEnabled();
  const submit = page.getByRole("button", { name: "Signing in..." });
  await expect(submit).toHaveAttribute("aria-disabled", "true");
  await submit.click({ force: true });
  release();
  await expect(page.getByRole("alert")).toHaveText(
    "Couldn't sign you in. Check your details and try again.",
  );
  expect(posts).toBe(1);
});

test("disabled or locked account: the one failure string (SR-014)", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (r) =>
    r.fulfill(json({ code: "unauthenticated" }, 401)),
  );
  await page.goto("/login");
  await fill(page);
  await expect(page.getByRole("alert")).toHaveText(
    "Couldn't sign you in. Check your details and try again.",
  );
});

test("rate-limited: remaining time shown, submit aria-disabled", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (r) =>
    r.fulfill(json({}, 429, { "Retry-After": "900" })),
  );
  await page.goto("/login");
  await fill(page);
  await expect(page.getByText(/Try again in 1[45]:\d\d/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  expect(await serious(page)).toEqual([]);
});

test("server unreachable", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (r) => r.abort());
  await page.goto("/login");
  await fill(page);
  await expect(page.getByRole("alert")).toContainText("Cannot reach the server");
});

test("SCR-004 forced password change", async ({ page }) => {
  await page.route("**/api/v1/auth/password", (r) => r.fulfill({ status: 204 }));
  await page.goto("/login/change-password");
  expect(await serious(page)).toEqual([]);
  await page.getByLabel("Current password").fill("old");
  await page.getByLabel("New password", { exact: true }).fill("correct horse battery");
  await page.getByLabel("Confirm new password").fill("correct horse battery");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByRole("heading", { name: "Password changed" })).toBeVisible();
});
