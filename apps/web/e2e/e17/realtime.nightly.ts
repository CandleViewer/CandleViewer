// E17-Q04 (#569): AC 2's and AC 3's budgets on real timers, measured on the shipped bundle and recorded as an
// annotation (`measured`). It runs in its own lane (`playwright.e17-nightly.config.ts`, `*.nightly.ts`), which the
// per-PR stub lane never matches: a real-time number is data for the nightly record, never a PR gate or a pack row.
import { expect, test } from "@playwright/test";
import { REALTIME, covers, openWorkspace, patient, region } from "./support";

test(`Q04-R01 the treatment within 2 s of a drop; a short outage healed within 10 s ${REALTIME}`, async ({
  page,
}) => {
  covers("AC-2", "AC-3");
  const harness = await openWorkspace(page);
  const dropped = Date.now();
  harness.kill();
  await patient(region(page)).toBeVisible();
  const shownMs = Date.now() - dropped;
  harness.restore();
  const restored = Date.now();
  await patient.poll(() => harness.authenticated()).toBe(2);
  const healedMs = Date.now() - restored;
  test.info().annotations.push({
    type: "measured",
    description: `treatment ${shownMs} ms; reconnect ${healedMs} ms`,
  });
  expect(shownMs).toBeLessThanOrEqual(2_000);
  expect(healedMs).toBeLessThanOrEqual(10_000);
});
