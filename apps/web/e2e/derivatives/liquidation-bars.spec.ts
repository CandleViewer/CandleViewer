// E24-Q02 (#772) PR 1: the SCR-054 liquidation bars, end to end (E24-D02 §6, §10, §11; E24-D04 A-16, A-25).
// Written against the E24-S06 stack before it merges: #5767 (cf2a5a4b4) and #5768 (fabcc2adf), on #5763–#5766.
// Names are that stack's `copy.ts`. The bars are `/market/metrics` `liquidation_notional` series (#5341's shape):
// `"0"` for a bar without prints, so zero and unknown are told apart only by the feed's coverage (#5767 BQ-2). The
// pane waits on that coverage, which the feed publishes from its animation-frame loop: every wait is `settle`/`shown`.
import { expect, test } from "@playwright/test";
import { seriousAxe } from "../support/axe";
import {
  barsPane,
  columnTexts,
  covers,
  fixtureBackend,
  liquidationPushes,
  openDerivatives,
  paneScope,
  settle,
  shown,
  sum,
  SYMBOL,
  type Backend,
} from "./support";

const BAR_MS = 15 * 60_000;
const barsTable = (page: Parameters<typeof barsPane>[0]) =>
  barsPane(page).getByRole("table", { name: new RegExp(`^Liquidation bars, ${SYMBOL}`, "u") });

/**
 * Eight 15 min bars ending at the paused "now": recording began 34 min before it (the default coverage), so the bars
 * before that are unknown, the empty ones after it are zero, and the last holds the burst's notional per side.
 */
function backendWithBars(): Backend {
  const backend = fixtureBackend();
  const last = Math.floor(backend.timeline.nowMs / BAR_MS) * BAR_MS;
  const starts = Array.from({ length: 8 }, (_, k) => last - (7 - k) * BAR_MS);
  const prints = liquidationPushes(backend.timeline).flat();
  const of = (side: "buy" | "sell") =>
    sum(prints.filter((p) => p.side === side).map((p) => p.notional_usd));
  backend.liqBars = {
    long: starts.map((t, k): [number, string] => [t, k === 7 ? of("sell") : "0"]),
    short: starts.map((t, k): [number, string] => [t, k === 7 ? of("buy") : "0"]),
  };
  return backend;
}

test("zero and unknown are different words, and the boundary names its time", async ({ page }) => {
  covers("BB-006-05", "AC Honesty guards", "D02 liq-partial", "D02 §11");
  await openDerivatives(page, { backend: backendWithBars() });
  const table = barsTable(page);
  await settle(page, async () => (await columnTexts(table, "State")).includes("recorded"));
  const states = await columnTexts(table, "State");
  expect(states).toContain("recorded");
  expect(states).toContain("zero");
  expect(states).toContain("not recorded"); // a "0" before coverage is never shown as zero
  expect(states).not.toContain("");
  await expect(barsPane(page).getByText(/^Recorded from .*\d{2}:\d{2}/u)).toBeVisible();
});

test("the threshold is applied from the keyboard and the legend states the filter", async ({
  page,
}) => {
  covers("US-DERIV-006 sc. 2", "D02 liq-bars", "D04 A-25");
  await openDerivatives(page, { backend: backendWithBars() });
  const pane = barsPane(page);
  const field = pane.getByRole("textbox", { name: "Minimum notional (USDT)" });
  await shown(page, field);
  await field.focus();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.type("50000");
  await page.keyboard.press("Enter"); // applies and keeps focus (D02 §13)
  await expect(field).toBeFocused();
  // #5768: "Showing prints ≥ …" when the server filters the bars, else it names the feed's filter; never silent
  await shown(page, pane.getByText(/≥ 50,000 USDT$/u));
});

test("keyboard: the display mode is a radio group; heatmap says why it is not drawn; no serious axe finding", async ({
  page,
}) => {
  covers("D04 A-16", "D02 liq-heatmap", "05 §3");
  await openDerivatives(page, { backend: backendWithBars() });
  const modes = barsPane(page).getByRole("radiogroup", { name: "Liquidation display" });
  const bars = modes.getByRole("radio", { name: "Bars" });
  await shown(page, bars);
  await expect(bars).toHaveAttribute("aria-checked", "true");
  await bars.focus();
  await page.keyboard.press("ArrowRight");
  const heatmap = modes.getByRole("radio", { name: "Heatmap" });
  await expect(heatmap).toBeFocused();
  await expect(heatmap).toHaveAttribute("aria-checked", "true");
  await expect(
    barsPane(page).getByText(
      "The realised-liquidation heatmap is not available yet. Switch to Bars to see recorded liquidations per bar.",
    ),
  ).toBeVisible();
  // a deliberate addition beyond the ticket's keyboard scope, feeding E24-Q04's audit
  // axe schedules its work with setTimeout(0), which never fires on the paused clock
  await page.clock.resume();
  expect(await seriousAxe(page, { include: paneScope(`Liquidation bars, ${SYMBOL}`) })).toEqual([]);
});
