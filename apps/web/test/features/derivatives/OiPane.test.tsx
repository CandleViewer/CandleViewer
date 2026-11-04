// E24-S01 (#776) slice 2: the CMP-186 OI sub-pane by role — the named region, the readout with its unit in
// the name, every state in text, the retry path, the keyboard table alternative, and axe over every story.
import { createRequire } from "node:module";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";
import { describe, expect, it, vi } from "vitest";
import * as stories from "../../../src/features/derivatives/oi/ui/OiPane.stories";
import { OiPane } from "../../../src/features/derivatives/oi/ui/OiPane";
import { INITIAL_OI_SNAPSHOT, type OiSnapshot } from "../../../src/features/derivatives/oi/oiFeed";

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

const region = () => screen.getByRole("region", { name: "Open interest, BTCUSDT" });

describe("OI pane (CMP-186, OiOnly)", () => {
  it("is a named region whose readout says the value with its unit", () => {
    render(stories.Populated.render());
    expect(within(region()).getByRole("heading", { name: "Open interest" })).toBeTruthy();
    // the readout is a CMP-036 term / definition pair
    expect(within(region()).getByRole("term").textContent).toBe("OI");
    const value = within(region()).getByRole("definition");
    expect(value.textContent).toContain("4.8B USDT (both sides)");
    expect(within(value).getByText("4.8 billion USDT, both sides")).toBeTruthy();
  });

  it("keeps an empty status region from mount and fills it on failure (B4)", () => {
    const failed: OiSnapshot = {
      ...INITIAL_OI_SNAPSHOT,
      history: { phase: "failed", status: 503, lastSuccessAtMs: null },
    };
    const { rerender } = render(
      <OiPane symbol="BTCUSDT" onRetry={vi.fn()} snapshot={INITIAL_OI_SNAPSHOT} />,
    );
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("");
    rerender(<OiPane symbol="BTCUSDT" onRetry={vi.fn()} snapshot={failed} />);
    expect(screen.getByRole("status")).toBe(status); // the same node, only its text changed
    expect(status.textContent).toBe("Couldn't load OI history");
    rerender(<OiPane symbol="BTCUSDT" onRetry={vi.fn()} snapshot={INITIAL_OI_SNAPSHOT} />);
    expect(screen.getByRole("status")).toBe(status);
    expect(status.textContent).toBe("");
  });

  it("puts the pane label at the host's heading level and the empty state one below (B6)", () => {
    const empty: OiSnapshot = {
      ...INITIAL_OI_SNAPSHOT,
      history: { phase: "ready", empty: true, truncated: null },
    };
    render(<OiPane symbol="SOLUSDT" onRetry={vi.fn()} snapshot={empty} headingLevel={2} />);
    expect(screen.getByRole("heading", { level: 2, name: "Open interest" })).toBeTruthy();
    expect(
      screen.getByRole("heading", { level: 3, name: "No open-interest history for SOLUSDT yet." }),
    ).toBeTruthy();
  });

  it("notes the table's cap and keeps the newest rows (B5)", () => {
    const rows = Array.from({ length: 205 }, (_, i) => ({
      tMs: i * 300_000,
      spanMs: 300_000,
      base: String(i),
      valueUsdt: null,
      source: "rest" as const,
      forming: false,
      asOfMs: i * 300_000,
    }));
    render(
      <OiPane
        symbol="BTCUSDT"
        onRetry={vi.fn()}
        defaultTableOpen
        snapshot={{ ...INITIAL_OI_SNAPSHOT, rows }}
      />,
    );
    const note = screen.getByText("Showing the newest 200 of 205.");
    expect(note.id).not.toBe("");
    const table = screen.getByRole("table");
    expect(table.getAttribute("aria-describedby")).toBe(note.id);
    expect(table.getAttribute("aria-describedby")).not.toBeNull();
    expect(screen.queryByRole("group")).toBeNull();
    expect(within(table).getAllByRole("row")).toHaveLength(201);
    expect(table.textContent).toContain("204");
    expect(table.textContent).not.toContain("1970-01-01 00:00:00");
  });

  it("keeps two gaps that start together as two rows, each its own key", () => {
    render(
      <OiPane
        symbol="BTCUSDT"
        onRetry={vi.fn()}
        defaultTableOpen
        snapshot={{
          ...INITIAL_OI_SNAPSHOT,
          gaps: [
            { fromMs: 300_000, toMs: 600_000, kind: "recorded" },
            { fromMs: 300_000, toMs: 900_000, kind: "recorded" },
          ],
        }}
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(table.hasAttribute("aria-describedby")).toBe(false);
  });

  it("marks a clipped history span in the table (A2)", () => {
    const t = Date.parse("2026-10-21T12:00:00Z");
    render(
      <OiPane
        symbol="BTCUSDT"
        onRetry={vi.fn()}
        defaultTableOpen
        snapshot={{
          ...INITIAL_OI_SNAPSHOT,
          rows: [
            {
              tMs: t,
              spanMs: 180_000,
              base: "1",
              valueUsdt: null,
              source: "rest",
              forming: false,
              asOfMs: t,
              clipped: true,
            },
          ],
        }}
      />,
    );
    expect(screen.getByRole("table").textContent).toContain("3 min (clipped)");
    expect(screen.queryByText(/Showing the newest/)).toBeNull();
  });

  it("falls back to base coin when only REST history is in (BQ 1)", () => {
    render(stories.RestOnly.render());
    expect(screen.getByText("51,347.25000000 BTC, both sides")).toBeTruthy();
  });

  it("labels the served delta as per bar (BQ 2)", () => {
    render(stories.WithDeltaPerBar.render());
    expect(screen.getByText("Open interest change per bar")).toBeTruthy();
    expect(region().textContent).toContain("+4.354 BTC");
  });

  it("says loading in text and is busy; says backfilling while live values show", () => {
    const { unmount } = render(stories.Loading.render());
    expect(screen.getByText("Loading open interest…")).toBeTruthy();
    expect(region().querySelector("[aria-busy='true']")).not.toBeNull();
    unmount();
    render(stories.Backfilling.render());
    expect(screen.getByText("Loading OI history…")).toBeTruthy();
  });

  it("offers Retry with the last loaded time on a failed backfill, and keeps focus in the pane", () => {
    const onRetry = vi.fn();
    render(
      <OiPane
        symbol="BTCUSDT"
        onRetry={onRetry}
        snapshot={{
          ...INITIAL_OI_SNAPSHOT,
          history: {
            phase: "failed",
            status: 503,
            lastSuccessAtMs: Date.parse("2026-10-21T09:14:02Z"),
          },
        }}
      />,
    );
    expect(screen.getByRole("status").textContent).toBe("Couldn't load OI history");
    expect(screen.getByText("Last loaded 09:14:02 UTC")).toBeTruthy();
    const retry = screen.getByRole("button", { name: "Retry" });
    retry.focus();
    expect(document.activeElement).toBe(retry);
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Open interest" }));
  });

  it("omits the last-loaded line when nothing ever loaded", () => {
    render(stories.BackfillFailedNeverLoaded.render());
    expect(screen.queryByText(/Last loaded/)).toBeNull();
  });

  it("shows the designed empty state, never a blank pane", () => {
    const { unmount } = render(stories.EmptyNeverRecorded.render());
    expect(
      screen.getByRole("heading", { name: "No open-interest history for SOLUSDT yet." }),
    ).toBeTruthy();
    expect(screen.getByText("Live OI is streaming now.")).toBeTruthy();
    unmount();
    render(stories.EmptyWithCoverageFrom.render());
    expect(screen.getByText("History starts 21 Oct 08:14 UTC.")).toBeTruthy();
    expect(screen.queryByText("Live OI is streaming now.")).toBeNull();
  });

  it("says stale in words with the last-good time, escalated at T2", () => {
    const { unmount } = render(stories.StaleT1.render());
    expect(screen.getByText("Stale, 7 seconds")).toBeTruthy();
    expect(region().textContent).toContain("last 09:14:02 UTC");
    expect(region().dataset["stale"]).toBe("t1");
    unmount();
    render(stories.StaleT2.render());
    expect(region().querySelector("[data-cmp='CMP-239']")?.getAttribute("data-level")).toBe(
      "strong",
    );
  });

  it("shows the native-granularity note", () => {
    render(stories.NativeGranularity.render());
    expect(screen.getByText("Native granularity 5 min")).toBeTruthy();
  });

  it("opens the table alternative from the keyboard: points, units, sources and the gap in words", () => {
    render(stories.Populated.render());
    const toggle = screen.getByRole("button", { name: "Show table" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.tabIndex).toBe(0);
    toggle.focus();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(toggle.textContent).toBe("Hide table");
    const table = screen.getByRole("table", { name: "Open interest, BTCUSDT, visible points" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "Time (UTC)",
      "Span",
      "OI (BTC, both sides)",
      "OI (USDT, both sides)",
      "Source",
    ]);
    const text = table.textContent ?? "";
    expect(text).toContain("REST history");
    expect(text).toContain("live");
    expect(text).toContain("gap · not recorded");
    expect(text).toContain("5 min, forming");
    expect(text).toContain("4,792,254,559.42");
    expect(text).toContain("no USDT value");
  });

  it("says so when no point is in view, and keeps only the chart's visible range", () => {
    const snap: OiSnapshot = { ...INITIAL_OI_SNAPSHOT };
    const { unmount } = render(
      <OiPane symbol="BTCUSDT" onRetry={vi.fn()} snapshot={snap} defaultTableOpen />,
    );
    expect(screen.getByText("No open-interest points in view.")).toBeTruthy();
    unmount();
    const live = Date.parse("2026-10-21T09:10:00Z");
    render(
      <OiPane
        symbol="BTCUSDT"
        onRetry={vi.fn()}
        defaultTableOpen
        visible={{ fromMs: live, toMs: live + 60_000 }}
        snapshot={{
          ...INITIAL_OI_SNAPSHOT,
          rows: [
            {
              tMs: 0,
              spanMs: 300_000,
              base: "1",
              valueUsdt: null,
              source: "rest",
              forming: false,
              asOfMs: 0,
            },
            {
              tMs: live,
              spanMs: 300_000,
              base: "2",
              valueUsdt: "3",
              source: "ws_ticker",
              forming: true,
              asOfMs: live,
            },
          ],
        }}
      />,
    );
    expect(screen.getAllByRole("row")).toHaveLength(2); // the header and the one point in view
  });

  it.each(Object.entries(stories).filter(([k]) => k !== "default"))(
    "has no serious axe violation: %s",
    async (_name, story) => {
      const { render: draw } = story as { render: () => JSX.Element };
      const { unmount } = render(draw());
      expect(await serious()).toEqual([]);
      unmount();
    },
    30_000, // axe under load (review r1 item 5)
  );
});
