import { arrive } from "./arrive";
import { expect, test } from "./fixtures";
import { PROBES } from "./probes";

// BQ-05 (a): an unmounted surface is an expected failure naming its ticket, never a silent skip. Arriving on
// the route (URL and session) is asserted as an ordinary step; only the surface's absence is the expectation,
// written as `not.toBeVisible`, which fails with the ticket's name the day the surface lands.
for (const probe of PROBES) {
  test(`E47-TC-${probe.cases.join("/")} ${probe.ticket}: ${probe.path}`, async ({ page }) => {
    await arrive(page, probe.path);
    for (const key of probe.keys ?? []) await page.keyboard.press(key);
    await expect(
      probe.find(page),
      `${probe.ticket} landed: E47-TC-${probe.cases.join("/")} is now a real journey; replace this probe`,
    ).not.toBeVisible({ timeout: 3_000 });
  });
}
