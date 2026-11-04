/**
 * E12-Q07 (#530) PR 1: the offline legs of the bar-mode a11y audit over the built SCR-045 shell and the polite
 * writer (report `docs/qa/a11y/e12-q07-bars-v1.md` §3). Oracles: E12-D11 §7 (the announcement budget, BG-09 and
 * BG-13), E12-D11's mirror caps (60 rows by default, cap 200, 1,800 nodes per pane) and E12-D07's parity rule (an
 * absent delta or CVD reads "—", never 0). Every verdict is agent-run (heuristic); no screen reader runs here.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { ChartDataTable } from "../../../src/chart/a11y/ChartDataTable";
import { NOT_AVAILABLE } from "../../../src/chart/a11y/copy";
import { createAmbientWriter, type AnnouncePrefs } from "../../../src/chart/a11y/politeWriter";
import type { ChartTableSeries } from "../../../src/chart/a11y/series";
import { clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { makeSeries } from "./fixture";

/** E12-D11's mirror caps (E06-D03 D1): rows by default, the row cap and the hard node cap per pane. */
const DEFAULT_ROWS = 60;
const ROW_CAP = 200;
const NODE_CAP = 1_800;
/** BG-13: at most two polite writes in any one second. */
const PER_SECOND = 2;

afterEach(() => {
  vi.useRealTimers();
  clearAnnouncements();
});

const focused = (): HTMLElement => document.activeElement as HTMLElement;
const press = (key: string): void => {
  fireEvent.keyDown(focused(), { key });
};
const barRows = (grid: HTMLElement): HTMLElement[] =>
  within(grid)
    .getAllByRole("row")
    .filter((r) => r.getAttribute("data-kind") === "bar");

function table(series: ChartTableSeries, initialBar?: number) {
  const say = vi.fn<(text: string) => void>();
  const ui = (s: ChartTableSeries): JSX.Element => (
    <ChartDataTable
      series={s}
      title="BTCUSDT 1m"
      focusOnOpen
      say={say}
      writeClipboard={async () => undefined}
      {...(initialBar === undefined ? {} : { initialBar })}
    />
  );
  const view = render(ui(series));
  return {
    say,
    grid: screen.getByRole("grid"),
    update: (s: ChartTableSeries) => view.rerender(ui(s)),
  };
}

/** The most entries of `times` (ms) inside any window of `width` ms. */
function maxInWindow(times: readonly number[], width: number): number {
  let best = 0;
  let lo = 0;
  for (let hi = 0; hi < times.length; hi++) {
    while ((times[hi] ?? 0) - (times[lo] ?? 0) >= width) lo++;
    best = Math.max(best, hi - lo + 1);
  }
  return best;
}

describe("Q07 windowing at 100 000 bars (E12-D11 mirror caps; ticket Performance notes)", () => {
  it("never materialises more than the row cap or the per-pane node cap, at open and after travel", () => {
    const { grid } = table(makeSeries({ bars: 100_000, levels: 3 }), 50_000);
    const measure = (): { rows: number; nodes: number } => ({
      rows: barRows(grid).length,
      nodes: grid.querySelectorAll("*").length,
    });
    const atOpen = measure();
    for (let i = 0; i < 40; i++) act(() => press("ArrowDown"));
    act(() => press("Enter")); // a bar's footprint levels join the drawn rows
    const afterTravel = measure();
    for (const m of [atOpen, afterTravel]) {
      expect(m.rows).toBeLessThanOrEqual(ROW_CAP);
      expect(m.nodes).toBeLessThanOrEqual(NODE_CAP);
    }
    // Recorded in the report (§3.2): the shell draws the cursor ± 30 rows, one over the mirror's 60-row default.
    expect(atOpen.rows).toBe(DEFAULT_ROWS + 1);
  });

  it("a forming-bar update at 100 000 bars rewrites only the drawn rows, never the off-screen data", () => {
    const series = makeSeries({ bars: 100_000, levels: 0 });
    const { grid, update } = table(series);
    const drawn = grid.querySelectorAll("*").length;
    const records: MutationRecord[] = [];
    const observer = new MutationObserver((batch) => records.push(...batch));
    observer.observe(grid, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
    });
    const close = Int32Array.from(series.candles.close);
    close[close.length - 1] = (close[close.length - 1] ?? 0) + 3;
    act(() => update({ ...series, candles: { ...series.candles, close } }));
    records.push(...observer.takeRecords());
    observer.disconnect();
    const added = records.reduce((n, r) => n + r.addedNodes.length, 0);
    expect(records.length).toBeGreaterThan(0); // the change reached the drawn last row
    expect(added).toBeLessThanOrEqual(drawn);
    expect(grid.querySelectorAll("*").length).toBe(drawn);
  });
});

describe("Q07 announcement budget (E12-D11 §7: BG-09, BG-13)", () => {
  it("BG-09: a held ↓ through the table writes no polite line per move; the reader follows focus", () => {
    const { say } = table(makeSeries({ bars: 100_000, levels: 3 }), 10_000);
    say.mockClear(); // the open's one line ("Data table, row …") is the user action's
    for (let i = 0; i < 60; i++) act(() => press("ArrowDown")); // 2 s of a 30 Hz key repeat
    expect(say).not.toHaveBeenCalled();
    expect(focused().closest("tr")).toHaveAttribute("data-bar", "10060");
  });

  it("BG-13: a forming bar's value at 20 Hz for 60 s writes at most two per second, each the latest", () => {
    vi.useFakeTimers();
    const prefs: AnnouncePrefs = { announce_prices: "always", verbosity: "normal" };
    const writes: { at: number; text: string }[] = [];
    const w = createAmbientWriter({
      fields: ["close"],
      prefs: () => prefs,
      say: (_p, text) => writes.push({ at: Date.now(), text }),
    });
    const start = Date.now();
    let last = "";
    for (let tick = 0; tick < 60 * 20; tick++) {
      last = `close ${64_000 + (tick % 97) * 0.5}`;
      w.set("close", last);
      vi.advanceTimersByTime(50);
    }
    vi.advanceTimersByTime(5_000); // the trailing write
    w.dispose();
    expect(
      maxInWindow(
        writes.map((x) => x.at - start),
        1_000,
      ),
    ).toBeLessThanOrEqual(PER_SECOND);
    expect(writes.length).toBeLessThanOrEqual(31); // 05 §6.2: one per 2 s, plus the trailing value
    expect(writes.at(-1)?.text).toBe(last);
  });
});

describe("Q07 parity (E12-D07 §6.1; the ticket's Security notes)", () => {
  it("a series without footprint shows delta and CVD as absent, never as zero", () => {
    const { grid } = table(makeSeries({ bars: 120, levels: 0 }));
    const rows = barRows(grid);
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      const cells = within(row).getAllByRole("gridcell");
      const absent = cells.slice(-2).map((c) => c.textContent ?? "");
      expect(absent).toHaveLength(2);
      for (const text of absent) {
        expect(text.endsWith(NOT_AVAILABLE)).toBe(true);
        expect(text).not.toMatch(/\d/);
      }
    }
  });
});
