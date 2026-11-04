// E24-S06 (#781): the table's lines go through the pane's one status node and never replay once a state sentence
// or another mode has replaced them. The table's own sources (sort, selection, row menus) are not in this table, so
// the table is stubbed with a button that says a line through the `announce` the pane hands it.
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../../../../src/features/derivatives/liquidations/bars/BarsTable", () => ({
  TABLE_ROWS: 200,
  BarsTable: ({ announce }: { announce: (t: string) => void }): JSX.Element => (
    <button type="button" onClick={() => announce("Sorted by bar")}>
      say
    </button>
  ),
}));

import { LiquidationBarsPane } from "../../../../../src/features/derivatives/liquidations/bars/LiquidationBarsPane";
import { buildBars } from "../../../../../src/features/derivatives/liquidations/bars/model";
import {
  COVERAGE,
  HOUR,
  NOW,
  SERVED_LONG,
  SERVED_SHORT,
} from "../../../../../src/features/derivatives/liquidations/bars/samples";
import { DEFAULT_LIQ_BAR_SETTINGS } from "../../../../../src/features/derivatives/liquidations/bars/settings";
import { viewOf } from "../../../../../src/features/derivatives/liquidations/bars/LiquidationBars.stories";

const bars = buildBars(SERVED_LONG, SERVED_SHORT, COVERAGE, HOUR);
const pane = (over: Partial<Parameters<typeof LiquidationBarsPane>[0]> = {}): JSX.Element => (
  <LiquidationBarsPane
    symbol="BTCUSDT"
    view={viewOf(bars)}
    coverage={{ kind: "ok", coverage: COVERAGE }}
    settings={DEFAULT_LIQ_BAR_SETTINGS}
    feedMinNotionalUsd={null}
    onSettingsChange={() => undefined}
    nowMs={NOW}
    {...over}
  />
);
const status = (): string => within(screen.getByRole("region")).getByRole("status").textContent;

describe("the table's lines in the pane's status node", () => {
  it("says the table's line in the one status node", () => {
    render(pane());
    fireEvent.click(screen.getByRole("button", { name: "say" }));
    expect(status()).toBe("Sorted by bar");
  });

  it("drops it when a state sentence takes the node, and does not replay it when that clears", () => {
    const { rerender } = render(pane());
    fireEvent.click(screen.getByRole("button", { name: "say" }));
    rerender(pane({ view: viewOf(bars, { stale: true, loadedAtMs: NOW - 60_000 }) }));
    expect(status()).toBe("Stale · last 11:29:00 UTC");
    rerender(pane());
    expect(status()).toBe("");
  });

  it("drops it on a mode change, so it does not replay on return", () => {
    const { rerender } = render(pane());
    fireEvent.click(screen.getByRole("button", { name: "say" }));
    rerender(pane({ settings: { ...DEFAULT_LIQ_BAR_SETTINGS, mode: "heatmap" } }));
    expect(status()).toBe("");
    rerender(pane());
    expect(status()).toBe("");
  });
});
