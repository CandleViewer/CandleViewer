import { expect, type Page } from "@playwright/test";
import { stubSession } from "../support/api";
import type { A11yScreen } from "./screens";

/**
 * Opens one screen for a collector and waits until it has rendered. A signed-in screen enters
 * through the app's own bootstrap with /api/v1/me answered at the network layer, and the call fails
 * unless the route guard let it in and its h1 rendered: a bounce to /login renders a <main> of its
 * own, so waiting for any <main> would pass on the wrong page (#3470).
 */
export async function openScreen(page: Page, s: A11yScreen): Promise<void> {
  // Stubs are per screen: one left behind by a signed-in screen would sign the next public one in.
  await page.unrouteAll({ behavior: "ignoreErrors" });
  if (s.signedIn) await stubSession(page, { role: s.signedIn.role });
  await page.goto(s.path);
  await page.getByRole("main").first().waitFor();
  if (!s.signedIn) return;
  const landed = new URL(page.url()).pathname;
  if (landed !== s.path) {
    throw new Error(
      `${s.id}: opened ${s.path} but landed on ${landed}; the session stub did not hold`,
    );
  }
  // expect gives up after its 5 s default; waitFor has no default timeout, so a missing h1 would
  // hold until the 300 s test timeout.
  await expect(
    page.getByRole("heading", { level: 1, name: s.signedIn.heading, exact: true }),
    `${s.id}: its h1 did not render`,
  ).toBeVisible();
}
