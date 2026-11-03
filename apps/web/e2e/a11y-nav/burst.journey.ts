import type { Page } from "@playwright/test";
import { arrive } from "./arrive";
import { installWsHarness, type WsHarness } from "../support/wsHarness";
import { expect, test } from "./fixtures";
import { politeBudget } from "./liveRegion";

// E47-Q03 AC4 (BQ-09 (a)): 500 messages through the deterministic WS harness; focus stays where it was, and the
// polite regions mutate within the s6.2 budget. The harness drives every frame, so the only time input is the
// burst's own duration, which the budget scales with.
const BURST = 500;

interface Watch {
  __polite: number;
}

async function open(page: Page): Promise<WsHarness> {
  const harness = await installWsHarness(page);
  await arrive(page, "/terminal");
  await expect.poll(() => harness.authenticated()).toBe(1);
  await page.evaluate(() => {
    const w = window as unknown as Watch;
    w.__polite = 0;
    for (const el of document.querySelectorAll('[aria-live="polite"]')) {
      new MutationObserver((rows) => (w.__polite += rows.length)).observe(el, {
        childList: true,
        characterData: true,
        subtree: true,
      });
    }
  });
  return harness;
}

/** Positive control: a polite region is mounted, and the watcher counts a mutation made here. */
async function watcherIsLive(page: Page): Promise<void> {
  const polite = page.locator('[aria-live="polite"]');
  expect(await polite.count(), "no polite region is mounted").toBeGreaterThan(0);
  const before = await page.evaluate(() => (window as unknown as Watch).__polite);
  await polite.first().evaluate((el) => el.appendChild(document.createTextNode("")));
  await expect
    .poll(() => page.evaluate(() => (window as unknown as Watch).__polite))
    .toBeGreaterThan(before);
  await page.evaluate(() => ((window as unknown as Watch).__polite = 0));
}

/** Sends the burst, then asserts the polite regions stayed within the coalescing budget. */
async function burstWithinBudget(page: Page, harness: WsHarness): Promise<void> {
  const began = Date.now();
  for (let i = 0; i < BURST; i++) harness.sendTicker("BTCUSDT");
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
  const budget = politeBudget(Date.now() - began);
  expect(await page.evaluate(() => (window as unknown as Watch).__polite)).toBeLessThanOrEqual(
    budget,
  );
}

// No route consumes a ticker topic yet (connection-chip.spec.ts), so no burst can reach a polite region: this is
// the watcher's self-check plus focus under load, NOT AC4 coverage. AC4 starts with the first ticker-consuming
// surface (E47-S01's chart); until then the case is the next test.
test("E47-TC-106 burst harness: the watcher is live and focus holds on a shell control (not AC4)", async ({
  page,
}) => {
  const harness = await open(page);
  await watcherIsLive(page);
  const link = page.getByRole("navigation").getByRole("link").first();
  await link.focus();
  await burstWithinBudget(page, harness);
  await expect(link).toBeFocused();
});

// The ticket's own scenario: the order ticket's quantity field (E10-S05). Arrival, session and the watcher are
// asserted first, as ordinary steps. Only then, while the field is missing, is the run marked an expected failure
// (`test.fail` called after them), so a broken arrival or watcher is a real failure; once the field exists the
// same body runs as the AC4 journey.
test("E47-TC-109 AC4 E10-S05: the quantity field keeps focus through the burst", async ({
  page,
}) => {
  const harness = await open(page);
  await watcherIsLive(page);
  const qty = page.getByRole("spinbutton", { name: /quantity/i });
  const mounted = await qty.waitFor({ state: "visible", timeout: 3_000 }).then(
    () => true,
    () => false,
  );
  test.fail(!mounted, "E10-S05: the order ticket is not mounted");
  await qty.focus({ timeout: 3_000 });
  await burstWithinBudget(page, harness);
  await expect(qty).toBeFocused();
});
