// E24-Q02 (#772) PR 1: the SCR-054 open-interest sub-pane, end to end (E24-D02 §4, §9, §11, §13; E24-D04 §9, §10).
// Written against the E24-S01 / S02 stack before it merges: #5769 (c711730a5), #5770 (829bd0d80), #5771 (61eb73abf)
// and #5773 (f30f87076). Every name below is that stack's `copy.ts`; a re-pin that renames one fails here loudly.
// Selectors are roles and accessible names (BQ 2); text is only ever asserted as content. The feed publishes only from
// its animation-frame loop (#5770), so every history or stream assertion waits through `settle` / `shown`.
import { expect, test } from "@playwright/test";
import { seriousAxe } from "../support/axe";
import {
  columnTexts,
  covers,
  fixtureBackend,
  goldenCase,
  noSampleCase,
  oiHistory,
  oiPane,
  openDerivatives,
  paneScope,
  settle,
  shown,
  SYMBOL,
} from "./support";

/** #5773's quadrant words, keyed by the `/market/metrics` `oi_price_quadrant` enum. */
const QUADRANT_WORDS: Readonly<Record<string, string>> = {
  long_buildup: "long build-up",
  short_covering: "short covering",
  short_buildup: "short build-up",
  long_unwind: "long unwind",
};
const oiTable = (page: Parameters<typeof oiPane>[0]) =>
  oiPane(page).getByRole("table", { name: new RegExp(`^Open interest, ${SYMBOL}`, "u") });
const sourcesInclude =
  (page: Parameters<typeof oiPane>[0], ...want: string[]) =>
  async () => {
    const sources = await columnTexts(oiTable(page), "Source");
    return want.every((w) => sources.includes(w));
  };

/** Opens the pane's table from the keyboard, as D02 §11's toggle asks: focus, then `Enter`. */
async function openTable(page: Parameters<typeof oiPane>[0]): Promise<void> {
  const show = oiPane(page).getByRole("button", { name: "Show table" });
  await shown(page, show);
  await show.focus();
  await page.keyboard.press("Enter");
  await shown(page, oiTable(page));
}

test("backfill then live: REST history first, the recorded ticker extends it", async ({ page }) => {
  covers("BB-001-01", "US-DERIV-001 sc. 1");
  const open = await openDerivatives(page);
  await shown(page, oiPane(page));
  await openTable(page);
  await settle(page, sourcesInclude(page, "REST history"));
  open.sendLiveOi();
  open.sendLiveOi();
  await settle(page, sourcesInclude(page, "REST history", "live"));
  // one history read, never a refetch when live begins (#5770 "backfills once, then extends live")
  expect(open.backend.calls.filter((c) => c === "open-interest")).toHaveLength(1);
});

test("backfill failure: the retry band, live OI still streaming, no invented last-loaded time", async ({
  page,
}) => {
  covers("BB-001-03", "AC Failure path", "D02 oi-backfill-failed");
  const backend = fixtureBackend();
  backend.oiStatus = 503;
  const open = await openDerivatives(page, { backend });
  const pane = oiPane(page);
  await shown(page, pane.getByText("Couldn't load OI history"));
  // D02 §4: `Last loaded …` only when a load once succeeded; none has here (BQ 8: the success-then-failure leg is
  // requested from E24-S01 on #776)
  await expect(pane.getByText(/^Last loaded /u)).toHaveCount(0);
  open.sendLiveOi();
  await openTable(page);
  await settle(page, sourcesInclude(page, "live"));
  const sources = await columnTexts(oiTable(page), "Source");
  expect(sources).not.toContain("REST history"); // a gap, never a line, where history failed
  // the retry reads again and the history arrives under the live points
  backend.oiStatus = 200;
  const reread = page.waitForResponse((r) => r.url().includes("/api/v1/market/open-interest?"));
  await pane.getByRole("button", { name: "Retry" }).focus();
  await page.keyboard.press("Enter");
  await reread;
  await settle(page, sourcesInclude(page, "REST history", "live"));
});

test("all four quadrants are named in words, with the golden's counts, in the key row and the table", async ({
  page,
}) => {
  covers("BB-002-02", "US-DERIV-002", "D02 oi-quadrants-on");
  const { bars } = goldenCase("btc_8h_15m");
  const counts = Object.entries(QUADRANT_WORDS).map(
    ([value, words]) => [words, bars.filter((b) => b.oi_price_quadrant === value).length] as const,
  );
  await openDerivatives(page);
  const key = oiPane(page).getByText(/^price · OI:/u);
  // every count is above zero in this golden, so a window without the golden's bars fails here
  expect(counts.every(([, n]) => n > 0)).toBe(true);
  for (const [words, n] of counts)
    await shown(page, key.filter({ hasText: new RegExp(`${words} ${String(n)}(?!\\d)`, "u") }));
  await openTable(page);
  const quadrants = await columnTexts(oiTable(page), "Quadrant");
  for (const [words] of counts) expect(quadrants).toContain(words);
});

test("a bar with no OI sample is unclassified, says why, and joins no quadrant", async ({
  page,
}) => {
  covers("AC Honesty guards", "D02 oi-no-sample", "US-DERIV-002 sc. 3");
  // the stale-open golden with its null bar emptied of REST rows (transform 4 in `support.ts`)
  const { bars, drops } = noSampleCase();
  const backend = fixtureBackend();
  backend.bars = bars;
  backend.oi = oiHistory(backend.timeline, drops);
  await openDerivatives(page, { backend });
  const key = oiPane(page).getByText(/^price · OI:/u);
  await shown(page, key.filter({ hasText: /(?<!\d)1 unclassified \(no OI sample\)/u }));
  await openTable(page);
  const quadrants = await columnTexts(oiTable(page), "Quadrant");
  expect(quadrants.filter((q) => q === "unclassified (no OI sample)")).toHaveLength(1);
  // the neutral hatch itself is canvas: E24-Q04 / the engine's golden images own the pixels; here the words
});

test("keyboard: the mode control and the table toggle are reachable and operable; no serious axe finding", async ({
  page,
}) => {
  covers("D04 A-08", "D04 §9.1", "05 §3");
  await openDerivatives(page);
  const pane = oiPane(page);
  // #5773 at f30f87076 ships a `group` of two pressed buttons where D04 A-08 draws a `switch` (BQ 3)
  const modes = pane.getByRole("group", { name: "Open interest display" });
  const absolute = modes.getByRole("button", { name: "Absolute" });
  const delta = modes.getByRole("button", { name: "Delta" });
  await shown(page, absolute);
  await expect(absolute).toHaveAttribute("aria-pressed", "true");
  await absolute.focus();
  await page.keyboard.press("Tab");
  await expect(delta).toBeFocused();
  await page.keyboard.press("Space");
  await expect(delta).toHaveAttribute("aria-pressed", "true");
  await expect(absolute).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Tab");
  await expect(pane.getByRole("button", { name: "Show table" })).toBeFocused();
  // a deliberate addition beyond the ticket's keyboard scope, feeding E24-Q04's audit
  // axe schedules its work with setTimeout(0), which never fires on the paused clock
  await page.clock.resume();
  expect(await seriousAxe(page, { include: paneScope(`Open interest, ${SYMBOL}`) })).toEqual([]);
});

test("a viewer session still sees market data", async ({ page }) => {
  covers("ticket Security notes", "US-DERIV-001");
  const open = await openDerivatives(page, { role: "viewer" });
  await shown(page, oiPane(page));
  open.sendLiveOi();
  await openTable(page);
  await settle(page, sourcesInclude(page, "live"));
});

test("an unauthenticated session is sent to login and reads no market data", async ({ page }) => {
  covers("ticket Security notes");
  const reads: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/v1/market/")) reads.push(r.url());
  });
  await page.route("**/api/v1/me", (r) => r.fulfill({ status: 401, body: "{}" }));
  await page.route("**/api/v1/me/**", (r) => r.fulfill({ status: 401, body: "{}" }));
  await page.goto("/terminal");
  await expect(page).toHaveURL(/\/login/u);
  await expect(oiPane(page)).toHaveCount(0);
  expect(reads).toEqual([]);
});
