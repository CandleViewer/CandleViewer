// E24-S05 (#780) slice 1: the feed by role — the named region and heading, the feed as a grid with units and side
// words, the bounded rows, the burst counter that is never a live region, the filter line, the freeze under
// Pause / focus with its `N new` count, and axe over every story.
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";
import { describe, expect, it, vi } from "vitest";
import * as stories from "../../../../src/features/derivatives/liquidations/ui/LiquidationPane.stories";
import { LiquidationPane } from "../../../../src/features/derivatives/liquidations/ui/LiquidationPane";
import type { LiqSnapshot } from "../../../../src/features/derivatives/liquidations/liquidationFeed";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

async function serious(): Promise<string[]> {
  // jsdom has no canvas; contrast is the Storybook / Playwright axe run's
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => v.id);
}

const noop = (): void => undefined;
const region = () => screen.getByRole("region", { name: "Liquidations, BTCUSDT" });
const grid = () => within(region()).getByRole("grid", { name: /Liquidation prints, BTCUSDT/ });
const bodyRows = () => within(grid()).getAllByRole("row").slice(1);

const next = (s: LiqSnapshot): LiqSnapshot => ({
  ...s,
  rows: [
    { ...stories.DESIGN_ROW, seq: s.newestSeq + 1, tsMs: stories.DESIGN_ROW.tsMs + 1000 },
    ...s.rows,
  ],
  newestSeq: s.newestSeq + 1,
});

describe("LiquidationPane (CMP-186, the feed)", () => {
  it("is a named region with a heading and the completeness sentence", () => {
    render(stories.Populated.render());
    expect(within(region()).getByRole("heading", { name: "Liquidations" })).toBeTruthy();
    expect(region().textContent).toContain(
      "Bybit publishes liquidations in 500 ms batches; every print is included — history is limited to what the recorder captured",
    );
  });

  it("is a grid whose headers carry the units and whose side cell is a word, not a colour", () => {
    render(stories.Populated.render());
    const headers = within(grid())
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "Time (UTC)",
      "Liquidated side",
      "Size (BTC)",
      "Bankruptcy price (p), USDT",
      "Notional (USDT)",
      "Cluster (×N)",
    ]);
    const first = bodyRows()[0];
    if (first === undefined) throw new Error("no row");
    const cells = within(first)
      .getAllByRole("gridcell")
      .map((c) => c.textContent);
    expect(cells).toEqual([
      "09:14:02",
      "Long liquidated ▼",
      "0.498 BTC",
      "82,751.20 USDT",
      "41,210.10 USDT",
      "×8",
    ]);
    expect(first.querySelector("[aria-hidden='true']")?.textContent).toBe("▼");
  });

  it("draws at most 40 rows in a cascade and shows the rate, never as a live region", () => {
    render(stories.Cascade.render());
    expect(bodyRows()).toHaveLength(40);
    expect(region().textContent).toContain("1,240 prints/s");
    const counter = screen.getByText("1,240 prints per second");
    // the counter sits in an `aria-live="off"` node with no announcing region around it (D02 §13)
    expect(counter.closest("[aria-live]")?.getAttribute("aria-live")).toBe("off");
    expect(counter.closest("[role='status'], [role='alert'], [role='log']")).toBeNull();
  });

  it("states the server-side filter", () => {
    render(stories.Filtered.render());
    expect(screen.getByText("Showing prints ≥ 50,000 USDT")).toBeTruthy();
  });

  it("never words an empty feed as no liquidations", () => {
    render(stories.Waiting.render());
    expect(screen.getByText("No prints received since the feed opened.")).toBeTruthy();
    expect(region().textContent).not.toMatch(/no liquidations/i);
  });

  it("holds the view while paused, counts what arrived, and shows the newest on demand", () => {
    const { rerender } = render(
      <LiquidationPane symbol="BTCUSDT" onRetry={noop} snapshot={stories.base} />,
    );
    const pause = screen.getByRole("button", { name: "Pause" });
    expect(pause.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(pause);
    expect(pause.getAttribute("aria-pressed")).toBe("true");
    const later = next(next(stories.base));
    rerender(<LiquidationPane symbol="BTCUSDT" onRetry={noop} snapshot={later} />);
    expect(bodyRows()).toHaveLength(2);
    const fresh = screen.getByRole("button", { name: "2 new prints, show newest" });
    expect(fresh.textContent).toBe("2 new");
    fireEvent.click(fresh);
    expect(bodyRows()).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Pause" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
  });

  it("holds the view while focus is in the table and resumes when it leaves", () => {
    const { rerender } = render(
      <LiquidationPane symbol="BTCUSDT" onRetry={noop} snapshot={stories.base} />,
    );
    const cell = within(grid()).getAllByRole("gridcell")[0];
    if (cell === undefined) throw new Error("no cell");
    act(() => cell.focus());
    fireEvent.focus(cell);
    rerender(<LiquidationPane symbol="BTCUSDT" onRetry={noop} snapshot={next(stories.base)} />);
    expect(bodyRows()).toHaveLength(2);
    expect(screen.getByRole("button", { name: "1 new prints, show newest" })).toBeTruthy();
    fireEvent.blur(cell, { relatedTarget: null });
    expect(bodyRows()).toHaveLength(3);
  });

  it("holds the view under the pointer", () => {
    const { rerender, container } = render(
      <LiquidationPane symbol="BTCUSDT" onRetry={noop} snapshot={stories.base} />,
    );
    const feed = container.querySelector(".cv-liq-pane__feed");
    if (feed === null) throw new Error("no feed");
    fireEvent.pointerEnter(feed);
    rerender(<LiquidationPane symbol="BTCUSDT" onRetry={noop} snapshot={next(stories.base)} />);
    expect(bodyRows()).toHaveLength(2);
    fireEvent.pointerLeave(feed);
    expect(bodyRows()).toHaveLength(3);
  });

  it("moves between rows with the arrow keys (the APG grid)", () => {
    render(stories.Populated.render());
    const cells = within(grid()).getAllByRole("gridcell");
    const first = cells[0];
    if (first === undefined) throw new Error("no cell");
    act(() => first.focus());
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(document.activeElement?.textContent).toBe("10:12:44");
  });

  it("names the first available time on a partial window, with the no-history sentence", () => {
    render(stories.Partial.render());
    expect(within(region()).getByText("since 09:14 UTC")).toBeTruthy();
    expect(
      within(region()).getByText(
        "No history before 09:14 UTC. Bybit publishes no liquidation history; earlier prints were not recorded.",
      ),
    ).toBeTruthy();
    expect(bodyRows()).toHaveLength(1);
  });

  it("keeps the chip and the counter together in a partial cascade", () => {
    render(stories.CascadePartial.render());
    expect(region().textContent).toContain("since 09:14 UTC");
    expect(region().textContent).toContain("1,240 prints/s");
  });

  it("says a never-recorded symbol has no history, never an empty list", () => {
    render(stories.NeverRecorded.render());
    const pane = screen.getByRole("region", { name: "Liquidations, SOLUSDT" });
    expect(
      within(pane).getByRole("heading", {
        name: "No liquidation history for SOLUSDT. Bybit publishes none, and this symbol has never been recorded.",
      }),
    ).toBeTruthy();
    expect(within(pane).getByText("Live liquidations are streaming now.")).toBeTruthy();
    expect(within(pane).queryByRole("grid")).toBeNull();
  });

  it("says a window before coverage is not 'no liquidations', never an empty list", () => {
    render(stories.BeforeCoverage.render());
    expect(
      within(region()).getByRole("heading", {
        name: "Not recorded before 09:14 UTC — this is not 'no liquidations'",
      }),
    ).toBeTruthy();
    expect(within(region()).queryByRole("grid")).toBeNull();
  });

  it("says what was recorded when the covered window holds no print", () => {
    render(stories.EmptyRecorded.render());
    expect(within(grid()).getByText("No prints recorded since 10:00 UTC.")).toBeTruthy();
  });

  it("offers Retry with the last loaded time, keeps the live rows and focus in the pane", () => {
    const onRetry = vi.fn();
    render(
      <LiquidationPane
        symbol="BTCUSDT"
        onRetry={onRetry}
        snapshot={{
          ...stories.base,
          history: {
            phase: "failed",
            status: 500,
            lastSuccessAtMs: Date.parse("2026-10-21T09:14:02Z"),
          },
        }}
      />,
    );
    expect(
      within(region()).getByText("Couldn't load liquidation history").getAttribute("role"),
    ).toBe("status");
    expect(screen.getByText("Last loaded 09:14:02 UTC")).toBeTruthy();
    expect(bodyRows()).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Liquidations" }));
  });

  it("says the server's coverage sentence on a 503", () => {
    render(stories.CoverageRetry.render());
    expect(
      within(region()).getByText("Recording metadata is not available yet; retry shortly."),
    ).toBeTruthy();
    expect(within(region()).queryByText(/Last loaded/)).toBeNull();
  });

  it("says loading in text: busy skeleton on a fresh pane, a caption while rows exist", () => {
    const { unmount } = render(stories.Loading.render());
    expect(screen.getByText("Loading liquidation history…")).toBeTruthy();
    expect(region().querySelector("[aria-busy='true']")).not.toBeNull();
    unmount();
    render(stories.Backfilling.render());
    expect(screen.getByText("Loading liquidation history…")).toBeTruthy();
    expect(region().querySelector(".cv-liq-pane__loading")).toBeNull();
  });

  it("says a truncated read", () => {
    render(stories.Truncated.render());
    expect(screen.getByText("Not every print in this window loaded.")).toBeTruthy();
  });

  it("names the topic's stale and disconnected states with the last print time", () => {
    const { unmount } = render(stories.Stale.render());
    expect(region().textContent).toContain("Stale · last 09:14:02 UTC");
    unmount();
    render(stories.Disconnected.render());
    expect(region().textContent).toContain("Disconnected · last 09:14:02 UTC");
  });

  it.each(
    Object.entries(stories).filter(([, s]) => typeof s === "object" && s !== null && "render" in s),
  )("story %s has no serious or critical axe violation", async (_name, story) => {
    render((story as { render: () => JSX.Element }).render());
    expect(await serious()).toEqual([]);
  });
});
