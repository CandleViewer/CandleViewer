import type { Page } from "@playwright/test";
import { stubSession } from "../support/api";
import { expect } from "./fixtures";

/**
 * Arrive on `path` signed in, and prove it: the URL is the probe's path (a guard bounce to /login would fail
 * here) and the shell's navigation landmark, which renders only for a session, is visible. Probes call this
 * outside their expected-failure assertion, so only the missing element is the expected failure.
 */
export async function arrive(page: Page, path: string): Promise<void> {
  await stubSession(page, { role: "owner" });
  await page.goto(path);
  await page.getByRole("main").first().waitFor({ timeout: 10_000 });
  await expect(page).toHaveURL(new RegExp(`^[^?#]*${path.replace(/[/.]/g, "\\$&")}(/|$|\\?|#)`));
  await expect(
    page.getByRole("navigation").first(),
    "no session: the shell did not render",
  ).toBeVisible();
}
