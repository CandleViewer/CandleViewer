// E24-S03 (#778) slice 1: the CMP-186 funding sub-pane by role: the named region, the interval in words, empty
// vs not recorded vs unknown (BQ 6), the persistent status region and the retry path with `last_success_at`,
// the table alternative under the group's "Show tables", and axe over every story.
import { createRequire } from "node:module";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as stories from "../../../src/features/funding/ui/FundingPane.stories";
import { buildFundingSeries } from "../../../src/features/funding/series";
import { FundingPane } from "../../../src/features/funding/ui/FundingPane";
import {
  INITIAL_FUNDING_SNAPSHOT,
  type FundingSnapshot,
} from "../../../src/features/funding/fundingFeed";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

async function serious(): Promise<string[]> {
  // jsdom has no layout; contrast is the Storybook a11y run's (`.storybook/main.ts` lists these stories)
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => v.id);
}

const region = (symbol = "BTCUSDT") => screen.getByRole("region", { name: `Funding, ${symbol}` });

describe("funding pane (CMP-186, FundingOnly)", () => {
  it("is a named region that states the served interval", () => {
    render(stories.Populated.render());
    expect(within(region()).getByRole("heading", { name: "Funding rate" })).toBeTruthy();
    expect(within(region()).getByText("settles every 8 h")).toBeTruthy();
  });

  it("states a 4 h interval and never an 8 h default when none is served", () => {
    const { unmount } = render(stories.FourHourInterval.render());
    expect(within(region("ETHUSDT")).getByText("settles every 4 h")).toBeTruthy();
    unmount();
    render(stories.IntervalUnknown.render());
    expect(within(region()).getByText("settlement interval not published")).toBeTruthy();
    expect(within(region()).queryByText(/8 h/)).toBeNull();
  });

  it("tells none settled from not recorded by coverage", () => {
    const { unmount } = render(stories.Empty.render());
    expect(
      screen.getByRole("heading", { level: 4, name: "No funding has settled for SOLUSDT yet" }),
    ).toBeTruthy();
    unmount();
    render(stories.NotRecorded.render());
    expect(
      screen.getByRole("heading", {
        name: "Funding history for SOLUSDT is not recorded for this range",
      }),
    ).toBeTruthy();
    expect(screen.queryByText(/has settled/)).toBeNull();
  });

  it("reads coverage that is not served as not recorded, never as none settled (BQ 6)", () => {
    render(stories.LongText.render());
    expect(
      screen.getByRole("heading", {
        name: "Funding history for 1000000BABYDOGEUSDT is not recorded for this range",
      }),
    ).toBeTruthy();
  });

  it("says the page bound ran out in the legend", () => {
    render(stories.Truncated.render());
    expect(within(region()).getByText("Recent history not loaded.")).toBeTruthy();
  });

  it("keeps one status node from mount and fills it on failure, with the last loaded time", () => {
    const failed: FundingSnapshot = {
      ...INITIAL_FUNDING_SNAPSHOT,
      history: { phase: "failed", status: 503 },
      lastSuccessAtMs: Date.parse("2023-11-15T09:14:02Z"),
    };
    const onRetry = vi.fn();
    const { rerender } = render(
      <FundingPane symbol="BTCUSDT" onRetry={onRetry} snapshot={INITIAL_FUNDING_SNAPSHOT} />,
    );
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("");
    rerender(<FundingPane symbol="BTCUSDT" onRetry={onRetry} snapshot={failed} />);
    expect(screen.getByRole("status")).toBe(status);
    expect(status.textContent).toBe("Couldn't load funding history");
    expect(screen.getByText("Last loaded 09:14:02 UTC")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading Funding" }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Funding rate" }));
  });

  it("claims no interval and no last loaded time after a failed first read", () => {
    render(stories.RetryFirst.render());
    expect(screen.getByRole("status").textContent).toBe("Couldn't load funding history");
    expect(screen.getByRole("button", { name: "Retry loading Funding" }).textContent).toBe("Retry");
    expect(screen.queryByText(/settle|Last loaded/)).toBeNull();
  });

  it("keeps the last good series in the table while the retry band shows", () => {
    render(stories.Retry.render());
    const table = screen.getByRole("table", { name: "Funding rate, BTCUSDT, settled" });
    expect(within(table).getAllByText("settled")).toHaveLength(4);
  });

  it("does not draw the empty-table sentence while the read is unanswered", () => {
    const { rerender } = render(
      <FundingPane
        symbol="BTCUSDT"
        onRetry={vi.fn()}
        snapshot={INITIAL_FUNDING_SNAPSHOT}
        showTables
      />,
    );
    expect(screen.queryByText("No settlements in view.")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(region().querySelector('[aria-busy="true"]')).not.toBeNull();
    // a failed first read has answered nothing either
    rerender(
      <FundingPane
        symbol="BTCUSDT"
        onRetry={vi.fn()}
        snapshot={{ ...INITIAL_FUNDING_SNAPSHOT, history: { phase: "failed", status: 503 } }}
        showTables
      />,
    );
    expect(screen.queryByText("No settlements in view.")).toBeNull();
    // once a read has answered with nothing, the sentence is the answer
    render(stories.Empty.render());
    expect(screen.queryByRole("table")).toBeNull();
    cleanup();
    render(
      <FundingPane
        symbol="SOLUSDT"
        onRetry={vi.fn()}
        showTables
        snapshot={{
          ...INITIAL_FUNDING_SNAPSHOT,
          history: { phase: "ready", empty: true, coverage: "covered", truncated: false },
        }}
      />,
    );
    expect(screen.getByText("No settlements in view.")).toBeTruthy();
  });

  it("keeps the last good series, legend and table while a retry is in flight", () => {
    const rows = 4;
    const last = Date.parse("2023-11-15T00:00:00Z");
    const settled = ["0.0001", "-0.00004", "0.00008", "0.0001"].map((rate, i) => ({
      tMs: last - (3 - i) * 8 * 3_600_000,
      rate,
    }));
    const retrying: FundingSnapshot = {
      history: { phase: "loading" },
      series: buildFundingSeries({
        settled,
        intervalMinutes: 480,
        coverage: { noCoverage: false, gaps: [] },
      }),
      lastSuccessAtMs: Date.parse("2023-11-15T09:14:02Z"),
    };
    render(<FundingPane symbol="BTCUSDT" onRetry={vi.fn()} snapshot={retrying} showTables />);
    expect(within(region()).getByText("settles every 8 h")).toBeTruthy();
    expect(within(screen.getByRole("table")).getAllByText("settled")).toHaveLength(rows);
  });

  it("says the instrument is unavailable, with no interval, table or settled claim", () => {
    render(stories.Unavailable.render());
    expect(screen.getByRole("status").textContent).toBe(
      "Funding unavailable for SOLUSDT: the instrument is not available right now.",
    );
    expect(screen.getByRole("button", { name: "Retry loading Funding" })).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText(/settles every/)).toBeNull();
  });

  it("shows the table only while the group's Show tables is pressed (E24-D04 A-03)", () => {
    render(stories.Populated.render());
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: /table/i })).toBeNull();
    cleanup();
    render(stories.TableOpen.render());
    const table = screen.getByRole("table", { name: "Funding rate, BTCUSDT, settled" });
    expect(within(table).getByText("minus 0.0040 percent")).toBeTruthy();
    expect(within(table).getByText("2023-11-14 00:00")).toBeTruthy();
    expect(within(table).getAllByText("8").length).toBeGreaterThan(0);
  });

  it("carries the stale tier on the region and shows the countdown in the legend", () => {
    render(stories.Stale.render());
    expect(region().getAttribute("data-stale")).toBe("t1");
    expect(within(region()).getByText("Stale 7s · last 15:55:41")).toBeTruthy(); // in text (F6)
    render(stories.EmptyWithCountdown.render()); // D03 S54-38: "No funding has settled … · next in 03:12:44"
    const empty = region("SOLUSDT");
    expect(
      within(empty).getByRole("heading", { name: "No funding has settled for SOLUSDT yet" }),
    ).toBeTruthy();
    expect(empty.querySelector(".cv-funding__digits")?.textContent).toBe(
      "next in 03:12:44 · 08:00 UTC",
    );
  });

  it.each(Object.entries(stories).filter(([k]) => k !== "default"))(
    "story %s has no serious axe violation",
    async (_name, story) => {
      const s = story as { render: () => JSX.Element };
      render(s.render());
      expect(await serious()).toEqual([]);
    },
    30_000,
  );
});
