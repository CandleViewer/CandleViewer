import { test, expect, type Page } from "@playwright/test";
import { buildCspPolicy } from "@candleviewer/config/csp-policy";
import { stubSession } from "../support/api";

// E43-T01 (SR-112, C-12.10): the built app, served by `vite preview` with the `<meta>` policy that
// `vite build` injected from the shared builder, raises no `securitypolicyviolation` on any rail
// screen. `style-src 'self'` (no 'unsafe-inline') is what is under test: React `style={}` goes
// through the CSSOM, so a violation here means something wrote an inline style attribute or a
// `<style>` element. Mirrors the Electron listener (apps/desktop/e2e/app-protocol.spec.ts). The API
// is stubbed at the network layer (C-13.5); the app code is not mocked.

interface Violation {
  readonly blockedURI: string;
  readonly effectiveDirective: string;
}

/** Records every violation on `document`, before any page script runs (survives reloads). */
async function recordViolations(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const seen: Violation[] = [];
    (globalThis as unknown as { cvCspViolations: Violation[] }).cvCspViolations = seen;
    document.addEventListener("securitypolicyviolation", (event) => {
      seen.push({ blockedURI: event.blockedURI, effectiveDirective: event.effectiveDirective });
    });
  });
}

const violations = (page: Page): Promise<Violation[]> =>
  page.evaluate(() => (globalThis as unknown as { cvCspViolations: Violation[] }).cvCspViolations);

test("the built page carries exactly the shared meta policy, strict style-src", async ({
  page,
}) => {
  await page.goto("/login");
  const meta = await page
    .locator('meta[http-equiv="Content-Security-Policy"]')
    .getAttribute("content");
  expect(meta).toBe(buildCspPolicy({ surface: "meta" }));
  expect(meta).not.toMatch(/unsafe-inline|unsafe-eval/u);
  expect(meta).toContain("style-src 'self';");
});

test("the listener is live: an injected inline script and <style> are blocked and reported", async ({
  page,
}) => {
  await recordViolations(page);
  await page.goto("/login");
  const ran = await page.evaluate(() => {
    const script = document.createElement("script");
    script.textContent = "document.documentElement.dataset.cvInline = 'ran';";
    document.head.append(script);
    const style = document.createElement("style");
    style.textContent = "body { outline: 3px solid red; }";
    document.head.append(style);
    return document.documentElement.dataset["cvInline"] === "ran";
  });
  expect(ran).toBe(false);
  await expect
    .poll(() => violations(page))
    .toContainEqual({
      blockedURI: "inline",
      effectiveDirective: "script-src-elem",
    });
  await expect
    .poll(() => violations(page))
    .toContainEqual({
      blockedURI: "inline",
      effectiveDirective: "style-src-elem",
    });
});

test("the sign-in screen raises no violation", async ({ page }) => {
  await recordViolations(page);
  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await violations(page)).toEqual([]);
});

const SCREENS = [
  "/terminal/last",
  "/rules",
  "/journal",
  "/replay",
  "/alerts",
  "/settings",
  "/admin",
] as const;

for (const path of SCREENS) {
  test(`${path} (owner) raises no securitypolicyviolation`, async ({ page }) => {
    await recordViolations(page);
    await stubSession(page, { role: "owner" });
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // The first paint after the heading: lazy chunks and the screen's own styles have been applied.
    await page.evaluate(
      () =>
        new Promise<void>((done) =>
          requestAnimationFrame(() => requestAnimationFrame(() => done())),
        ),
    );
    expect(await violations(page)).toEqual([]);
  });
}
