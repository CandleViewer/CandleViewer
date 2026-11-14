// E24-Q02 (#772) PR 1: the SCR-054 liquidation feed, end to end (E24-D02 §6, §9, §13, §15; E24-D04 A-17, A-18).
// Written against the E24-S05 stack before it merges: #5763 (82b4b1502), #5764 (fd683d73b), #5765 (a3380fb26) and
// #5766 (2c19b8da0). Names are that stack's `copy.ts`. Prints are #5273's burst fixture (BQ 5), pushed through the
// fake gateway as `liquidations.BTCUSDT` frames. The feed flushes history, coverage and prints only from its
// animation-frame loop (#5763), so every such assertion waits through `settle` / `shown` on the paused clock.
import { expect, test } from "@playwright/test";
import { seriousAxe } from "../support/axe";
import {
  advance,
  columnTexts,
  covers,
  feedPane,
  fixtureBackend,
  liquidationPushes,
  openDerivatives,
  paneScope,
  settle,
  shown,
  SYMBOL,
} from "./support";

const COMPLETENESS =
  "Bybit publishes liquidations in 500 ms batches; every print is included — history is limited to what the recorder captured";
const grid = (page: Parameters<typeof feedPane>[0]) => feedPane(page).getByRole("grid");
const iso = (ms: number): string => new Date(ms).toISOString();

test("the partial-history chip names the first recorded time", async ({ page }) => {
  covers("BB-005-03", "AC Honesty guards", "D02 liq-partial");
  await openDerivatives(page); // coverage begins 34 min before now, inside the window
  const pane = feedPane(page);
  await shown(page, pane.getByText(/^since .*\d{2}:\d{2}/u));
  await expect(
    pane.getByText(
      /^No history before .*\d{2}:\d{2}.*\. Bybit publishes no liquidation history; earlier prints were not recorded\.$/u,
    ),
  ).toBeVisible();
});

test("a window before coverage says 'not recorded', never an empty list", async ({ page }) => {
  covers("BB-005-04", "AC Honesty guards", "D02 liq-before-coverage");
  const backend = fixtureBackend();
  backend.liqCoverage = {
    first_available_ts: iso(backend.timeline.nowMs - 34 * 60_000),
    covered_from: null,
    covered_to: null,
    no_coverage: true,
  };
  await openDerivatives(page, { backend });
  const pane = feedPane(page);
  await shown(
    page,
    pane.getByText(/^Not recorded before .*\d{2}:\d{2}.* — this is not 'no liquidations'$/u),
  );
  // asserted after the state has rendered: no grid at all, so no empty list
  await expect(grid(page)).toHaveCount(0);
});

test("a symbol never recorded says so, and that live prints still stream", async ({ page }) => {
  covers("D02 liq-never-recorded", "added state 4");
  const backend = fixtureBackend();
  backend.liqCoverage = {
    first_available_ts: null,
    covered_from: null,
    covered_to: null,
    no_coverage: true,
  };
  const open = await openDerivatives(page, { backend });
  const pane = feedPane(page);
  await shown(
    page,
    pane.getByText(
      `No liquidation history for ${SYMBOL}. Bybit publishes none, and this symbol has never been recorded.`,
    ),
  );
  open.sendLiquidations(liquidationPushes(backend.timeline)[0] ?? []);
  await shown(page, pane.getByText("Live liquidations are streaming now."));
});

test("prints stream in with their side in words, under the completeness sentence", async ({
  page,
}) => {
  covers("US-DERIV-005", "D02 liq-feed", "D04 §9.5");
  const backend = fixtureBackend();
  const open = await openDerivatives(page, { backend });
  const pushes = liquidationPushes(backend.timeline);
  for (const push of pushes) {
    open.sendLiquidations(push);
    await advance(page, 500); // Bybit's push cadence; the client buckets per 250 ms
  }
  const sidesNow = () => columnTexts(grid(page), "Liquidated side");
  // both sides have landed: `Sell` prints are longs liquidated, `Buy` prints shorts
  await settle(page, async () => {
    const sides = await sidesNow();
    return ["Long liquidated", "Short liquidated"].every((w) => sides.some((s) => s.includes(w)));
  });
  const sides = await sidesNow();
  expect(sides.some((s) => /\b(Buy|Sell)\b/u.test(s))).toBe(false); // never the order side
  await expect(feedPane(page).getByText(COMPLETENESS)).toBeVisible();
});

test("keyboard: Pause freezes the feed and counts what arrived; the count resumes it", async ({
  page,
}) => {
  covers("D04 A-17", "D02 §6 feed cadence", "WCAG 2.2.2");
  const backend = fixtureBackend();
  const open = await openDerivatives(page, { backend });
  const [first = [], second = []] = liquidationPushes(backend.timeline);
  open.sendLiquidations(first);
  await shown(page, grid(page).getByRole("row").nth(1));
  const pause = feedPane(page).getByRole("button", { name: "Pause" });
  await expect(pause).toHaveAttribute("aria-pressed", "false");
  await pause.focus();
  await page.keyboard.press("Space");
  await expect(pause).toHaveAttribute("aria-pressed", "true");
  const before = await grid(page).getByRole("row").count();
  open.sendLiquidations(second);
  // the second push has landed once the count shows; only then is "frozen" a claim about it
  const fresh = feedPane(page).getByRole("button", { name: /^\d+ new prints?, show newest$/u });
  await shown(page, fresh);
  await expect(grid(page).getByRole("row")).toHaveCount(before); // frozen: no row moves under the reader
  await fresh.focus();
  await page.keyboard.press("Enter");
  await settle(page, async () => (await grid(page).getByRole("row").count()) > before);
  // a deliberate addition beyond the ticket's keyboard scope, feeding E24-Q04's audit
  // axe schedules its work with setTimeout(0), which never fires on the paused clock
  await page.clock.resume();
  expect(await seriousAxe(page, { include: paneScope(`Liquidations, ${SYMBOL}`) })).toEqual([]);
});

test("a failed history read shows its retry band while live prints keep arriving", async ({
  page,
}) => {
  covers("AC Failure path", "D02 liq-history-failed");
  const backend = fixtureBackend();
  backend.liqStatus = 503;
  const open = await openDerivatives(page, { backend });
  const pane = feedPane(page);
  await shown(page, pane.getByText("Couldn't load liquidation history"));
  await expect(pane.getByRole("button", { name: "Retry loading Liquidations" })).toBeVisible();
  await expect(pane.getByText(/^Last loaded /u)).toHaveCount(0); // nothing ever loaded (BQ 8)
  open.sendLiquidations(liquidationPushes(backend.timeline)[0] ?? []);
  await shown(page, grid(page).getByRole("row").nth(1));
});
