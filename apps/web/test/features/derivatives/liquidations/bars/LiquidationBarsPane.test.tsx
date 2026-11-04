// E24-S06 (#781) slice 2: the bars pane by role — the legend and the side words, the threshold line that never claims
// a filter the server does not apply, the boundary label, zero versus unknown in words in the table alternative,
// every state, the controls, the connected pane's read lifecycle, and axe over every story.
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectedLiquidationBars } from "../../../../../src/features/derivatives/liquidations/bars/ConnectedLiquidationBars";
import * as stories from "../../../../../src/features/derivatives/liquidations/bars/LiquidationBars.stories";
import {
  COVERAGE,
  DAY_COVERAGE,
  FIRST,
  HOUR,
  NOW,
  SERVED_LONG,
  SERVED_SHORT,
} from "../../../../../src/features/derivatives/liquidations/bars/samples";
import { TABLE_ROWS } from "../../../../../src/features/derivatives/liquidations/bars/BarsTable";
import type {
  BarsRead,
  BarsRequest,
} from "../../../../../src/features/derivatives/liquidations/bars/barsRead";
import type { LiqSnapshot } from "../../../../../src/features/derivatives/liquidations/liquidationFeed";
import { buildBars } from "../../../../../src/features/derivatives/liquidations/bars/model";
import { LiquidationBarsPane } from "../../../../../src/features/derivatives/liquidations/bars/LiquidationBarsPane";
import {
  DEFAULT_LIQ_BAR_SETTINGS,
  feedMinNotional,
  useLiqBarSettings,
} from "../../../../../src/features/derivatives/liquidations/bars/settings";

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

const region = () => screen.getByRole("region", { name: "Liquidation bars, BTCUSDT" });
const rows = () => within(within(region()).getByRole("table")).getAllByRole("row").slice(1);
const cells = (row: HTMLElement): string[] =>
  within(row)
    .getAllByRole("cell")
    .map((c) => c.textContent.replace(/\s+/g, " ").trim());

describe("LiquidationBarsPane (CMP-186, the bars)", () => {
  it("is a named region with a heading, the side words as the legend and the units in the headers", () => {
    render(stories.PartialBoundary.render());
    expect(within(region()).getByRole("heading", { name: "Liquidation bars" })).toBeTruthy();
    expect(region().textContent).toContain("Short liquidated ▲ above · Long liquidated ▼ below");
    expect(
      within(region())
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Bar (UTC)", "Long liquidated (USDT)", "Short liquidated (USDT)", "State"]);
    expect(
      within(region()).getByRole("table", { name: /Liquidation bars, BTCUSDT, 1 h bars/ }),
    ).toBeTruthy();
  });

  it("labels the boundary from the coverage and reads unknown bars in words, never as a zero (sc. 4, 5)", () => {
    render(stories.PartialBoundary.render());
    expect(region().querySelector("[data-cv-boundary]")?.textContent).toBe(
      "Recorded from 09:14 UTC",
    );
    // newest first: 11:00 recorded, 10:00 a genuine zero, then three bars that read "not recorded"
    expect(rows().map(cells)).toEqual([
      ["11:00", "2,900,000.50 USDT", "800,000.25 USDT", "recorded"],
      ["10:00", "0.00 USDT", "0.00 USDT", "zero"],
      ["09:00", "not recorded", "not recorded", "not recorded"],
      ["08:00", "not recorded", "not recorded", "not recorded"],
      ["07:00", "not recorded", "not recorded", "not recorded"],
    ]);
  });

  it("carries the unit in each figure's accessible name once, hidden beside the header's own (D02 §11)", () => {
    render(stories.PartialBoundary.render());
    const [recorded, zero, unknown] = rows();
    const hidden = (r: HTMLElement | undefined): string[] =>
      [...(r?.querySelectorAll(".cv-visually-hidden") ?? [])].map((n) => n.textContent.trim());
    expect(hidden(recorded)).toEqual(["USDT", "USDT"]);
    expect(hidden(zero)).toEqual(["USDT", "USDT"]);
    // the cell's name is the figure and its unit, once: "2,900,000.50 USDT", not "… USDT USDT"
    expect(cells(recorded as HTMLElement).slice(1, 3)).toEqual([
      "2,900,000.50 USDT",
      "800,000.25 USDT",
    ]);
    // an unknown bar has no figure and so no unit: it reads "not recorded"
    expect(hidden(unknown)).toEqual([]);
    expect(cells(unknown as HTMLElement).slice(1, 3)).toEqual(["not recorded", "not recorded"]);
  });

  it("marks a straddling bar's state with when its recording began", () => {
    render(stories.StraddlingBar.render());
    expect(rows().map((r) => cells(r)[3])).toEqual([
      "recorded",
      "zero",
      "recorded from 09:14 UTC",
      "not recorded",
      "not recorded",
    ]);
  });

  it("shows the bars on a UTC day boundary with the date on the other day (sc. 2)", () => {
    render(stories.DayBoundary.render());
    expect(rows().map((r) => cells(r)[0])).toEqual([
      "02:00",
      "01:00",
      "00:00",
      "20 Oct 23:00",
      "20 Oct 22:00",
    ]);
    expect(region().querySelector("[data-cv-boundary]")).toBeNull();
  });

  it("states no filter line at 0, and never a filter the server does not apply (sc. 3, BQ-1)", () => {
    const { unmount } = render(stories.PartialBoundary.render());
    expect(region().textContent).not.toMatch(/feed ≥|Showing prints/);
    unmount();
    render(stories.Filtered.render());
    expect(region().textContent).toContain("Bars: all prints · feed ≥ 50,000 USDT");
    expect(region().textContent).not.toContain("Showing prints");
  });

  it("reads the crosshair's bar with units, and an unknown bar in words", () => {
    const { unmount } = render(stories.CrosshairRecorded.render());
    expect(region().textContent).toContain(
      "11:00 · Long liquidated ▼ 2,900,000.50 USDT · Short liquidated ▲ 800,000.25 USDT",
    );
    unmount();
    render(stories.CrosshairUnknown.render());
    // the readout paragraph is exactly the words: no figure, no zero
    expect(within(region()).getByText("07:00 · not recorded").tagName).toBe("P");
  });

  it("discloses the history bound and an unreadable-value count", () => {
    const { unmount } = render(stories.HistoryBound.render());
    expect(region().textContent).toContain("Showing the newest 57 bars.");
    unmount();
    render(stories.Malformed.render());
    expect(region().textContent).toContain("2 values were unreadable and shown as not recorded.");
  });

  it("caps the table at its rows and says so", () => {
    const long = new Map(
      Array.from(
        { length: 250 },
        (_, i) => [HOUR * i + Date.parse("2026-10-01T00:00:00Z"), "1"] as const,
      ),
    );
    const bars = buildBars(long, long, DAY_COVERAGE, HOUR);
    render(
      <LiquidationBarsPane
        symbol="BTCUSDT"
        view={stories.viewOf(bars)}
        coverage={{ kind: "ok", coverage: DAY_COVERAGE }}
        settings={DEFAULT_LIQ_BAR_SETTINGS}
        feedMinNotionalUsd={null}
        onSettingsChange={() => undefined}
        nowMs={NOW}
      />,
    );
    expect(region().textContent).toContain("Table shows the newest 200 of 250 bars.");
    // the cut keeps the NEWEST 200, newest first: bar 249 at the top, bar 50 (the 51st) at the bottom
    // (DOM reads: 200 role queries would outlive the test timeout)
    const times = [...region().querySelectorAll("tbody tr")].map(
      (r) => r.querySelector("td, th")?.textContent.trim() ?? "",
    );
    expect(times).toHaveLength(TABLE_ROWS);
    expect(times[0]).toBe("09:00");
    expect(times.at(-1)).toBe("3 Oct 02:00");
    expect(times).not.toContain("3 Oct 01:00");
  });
});

describe("states", () => {
  it("loading: a busy skeleton and the words, no table", () => {
    render(stories.Loading.render());
    expect(region().querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(region().textContent).toContain("Loading liquidation bars…");
    expect(within(region()).queryByRole("table")).toBeNull();
  });

  it("waits for coverage rather than drawing bars it cannot classify", () => {
    render(stories.CoveragePending.render());
    expect(region().textContent).toContain("Waiting for recording coverage before drawing bars.");
    expect(within(region()).queryByRole("table")).toBeNull();
  });

  it("coverage failed: no zero is drawn, and Retry reads the coverage again", () => {
    const retry = vi.fn();
    render(
      <LiquidationBarsPane
        symbol="BTCUSDT"
        view={stories.viewOf([])}
        coverage={{ kind: "failed", onRetry: retry }}
        settings={DEFAULT_LIQ_BAR_SETTINGS}
        feedMinNotionalUsd={null}
        onSettingsChange={() => undefined}
        nowMs={NOW}
      />,
    );
    expect(within(region()).queryByRole("table")).toBeNull();
    fireEvent.click(
      within(region()).getByRole("button", { name: "Retry loading Liquidation bars" }),
    );
    expect(retry).toHaveBeenCalledOnce();
  });

  it("failed read: the retry band with its action; a 422 says the server does not compute it yet", () => {
    const retry = vi.fn();
    const { unmount } = render(
      <LiquidationBarsPane
        symbol="BTCUSDT"
        view={stories.viewOf([], { phase: "failed", error: { status: 503, code: null }, retry })}
        coverage={{ kind: "ok", coverage: COVERAGE }}
        settings={DEFAULT_LIQ_BAR_SETTINGS}
        feedMinNotionalUsd={null}
        onSettingsChange={() => undefined}
        nowMs={NOW}
      />,
    );
    expect(region().textContent).toContain("Couldn't load liquidation bars");
    fireEvent.click(
      within(region()).getByRole("button", { name: "Retry loading Liquidation bars" }),
    );
    expect(retry).toHaveBeenCalledOnce();
    unmount();
    render(stories.NotComputed.render());
    expect(region().textContent).toContain(
      "Liquidation bars are not available on this server yet.",
    );
  });

  it("a 422 with any other detail is the generic failure: its Retry stays", () => {
    const retry = vi.fn();
    render(
      <LiquidationBarsPane
        symbol="BTCUSDT"
        view={stories.viewOf([], {
          phase: "failed",
          error: { status: 422, code: "validation_failed", detail: "BTCUSDT is not listed" },
          retry,
        })}
        coverage={{ kind: "ok", coverage: COVERAGE }}
        settings={DEFAULT_LIQ_BAR_SETTINGS}
        feedMinNotionalUsd={null}
        onSettingsChange={() => undefined}
        nowMs={NOW}
      />,
    );
    expect(region().textContent).toContain("Couldn't load liquidation bars");
    expect(region().textContent).not.toContain("not available on this server yet");
    fireEvent.click(
      within(region()).getByRole("button", { name: "Retry loading Liquidation bars" }),
    );
    expect(retry).toHaveBeenCalledOnce();
  });

  it("stale: the last good bars stay, marked with their time", () => {
    render(stories.Stale.render());
    expect(region().textContent).toContain("Stale · last 11:25:00 UTC");
    expect(rows()).toHaveLength(5);
  });

  it("before coverage: the sentence, no table, no zero (S54-47)", () => {
    render(stories.BeforeCoverage.render());
    expect(region().textContent).toContain("Not recorded before");
    expect(region().textContent).toContain("this is not 'no liquidations'");
    expect(within(region()).queryByRole("table")).toBeNull();
  });

  it("never recorded: the sentence and no table (S54-46)", () => {
    render(stories.NeverRecorded.render());
    const r = screen.getByRole("region", { name: "Liquidation bars, SOLUSDT" });
    expect(r.textContent).toContain("No liquidation history for SOLUSDT.");
    expect(within(r).queryByRole("table")).toBeNull();
  });

  it("empty: the table's own empty state, never a zero", () => {
    render(stories.Empty.render());
    expect(region().textContent).toContain("The server returned no bars for this range.");
  });

  it("heatmap: the note, no bars, never bucketed on the client (BQ-6)", () => {
    render(stories.HeatmapPending.render());
    expect(region().textContent).toContain(
      "The realised-liquidation heatmap is not available yet.",
    );
    expect(within(region()).queryByRole("table")).toBeNull();
  });
});

describe("controls", () => {
  const mount = (
    onSettingsChange = vi.fn(),
    settings = DEFAULT_LIQ_BAR_SETTINGS,
  ): ReturnType<typeof vi.fn> => {
    render(
      <LiquidationBarsPane
        symbol="BTCUSDT"
        view={stories.viewOf(buildBars(SERVED_LONG, SERVED_SHORT, COVERAGE, HOUR))}
        coverage={{ kind: "ok", coverage: COVERAGE }}
        settings={settings}
        feedMinNotionalUsd={null}
        onSettingsChange={onSettingsChange}
        nowMs={NOW}
      />,
    );
    return onSettingsChange;
  };

  it("switches Bars and Heatmap as a radio group with Bars checked by default", () => {
    const change = mount();
    const group = within(region()).getByRole("radiogroup", { name: "Liquidation display" });
    expect(within(group).getByRole("radio", { name: "Bars" }).getAttribute("aria-checked")).toBe(
      "true",
    );
    fireEvent.click(within(group).getByRole("radio", { name: "Heatmap" }));
    expect(change).toHaveBeenCalledWith({ mode: "heatmap" });
  });

  it("commits a valid minimum notional on blur and on Enter, and refuses an invalid one in words", () => {
    const change = mount();
    const field = within(region()).getByRole("textbox", { name: "Minimum notional (USDT)" });
    fireEvent.change(field, { target: { value: "50000" } });
    fireEvent.blur(field);
    expect(change).toHaveBeenLastCalledWith({ minNotionalUsd: "50000" });
    fireEvent.change(field, { target: { value: "75000.5" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(change).toHaveBeenLastCalledWith({ minNotionalUsd: "75000.5" });
    change.mockClear();
    fireEvent.change(field, { target: { value: "-1" } });
    fireEvent.blur(field);
    expect(change).not.toHaveBeenCalled();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(region().textContent).toContain("Enter a number, 0 or more.");
  });
});

describe("ConnectedLiquidationBars", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  const OK: BarsRead = { kind: "ok", long: SERVED_LONG, short: SERVED_SHORT, malformed: 0 };
  type Snap = Pick<LiqSnapshot, "coverage" | "history" | "minNotionalUsd">;
  const snapshot = (
    coverage: typeof COVERAGE | null,
    minNotionalUsd: string | null,
    phase: "loading" | "failed" = "loading",
  ): Snap => {
    if (coverage !== null) {
      return { coverage, minNotionalUsd, history: { phase: "ready", coverage, truncated: null } };
    }
    return {
      coverage,
      minNotionalUsd,
      history:
        phase === "failed"
          ? { phase: "failed", status: 503, lastSuccessAtMs: null }
          : { phase: "loading" },
    };
  };
  const flush = (): Promise<void> => act(async () => void (await vi.advanceTimersByTimeAsync(0)));

  /** The host's job (SCR-054): one settings source for the feed's filter and the bars. */
  function Host({
    coverage = COVERAGE,
    phase,
    read,
    onRetryCoverage = () => undefined,
  }: {
    coverage?: typeof COVERAGE | null;
    phase?: "loading" | "failed";
    read: (req: BarsRequest) => Promise<BarsRead>;
    onRetryCoverage?: () => void;
  }): JSX.Element {
    const [settings, change] = useLiqBarSettings();
    const feedFilter = feedMinNotional(settings);
    return (
      <>
        <p>{`feed filter: ${feedFilter ?? "none"}`}</p>
        <ConnectedLiquidationBars
          symbol="BTCUSDT"
          param="60"
          snapshot={snapshot(coverage, feedFilter, phase)}
          settings={settings}
          onSettingsChange={change}
          onRetryCoverage={onRetryCoverage}
          read={read}
        />
      </>
    );
  }
  const reads = (): { calls: BarsRequest[]; read: (req: BarsRequest) => Promise<BarsRead> } => {
    const calls: BarsRequest[] = [];
    return {
      calls,
      read: (req) => {
        calls.push(req);
        return Promise.resolve(OK);
      },
    };
  };
  const commit = (value: string): void => {
    const field = within(region()).getByRole("textbox", { name: "Minimum notional (USDT)" });
    fireEvent.change(field, { target: { value } });
    fireEvent.blur(field);
  };

  it("reads the bars once and masks them with the feed's coverage; a threshold commit costs no re-read", async () => {
    const { calls, read } = reads();
    render(<Host read={read} />);
    await flush();
    expect(calls).toHaveLength(1);
    expect(rows()).toHaveLength(5);
    commit("50000");
    await flush();
    expect(calls).toHaveLength(1); // the server does not apply it (BQ-1): same key, no blank, no read
    expect(calls.every((c) => !c.serverThreshold)).toBe(true);
    expect(rows()).toHaveLength(5);
  });

  it("gives the feed and the bars one threshold: the legend states what the feed has applied", async () => {
    const { read } = reads();
    render(<Host read={read} />);
    await flush();
    expect(screen.getByText("feed filter: none")).toBeTruthy();
    expect(region().textContent).not.toMatch(/feed ≥/);
    commit("50000");
    await flush();
    expect(screen.getByText("feed filter: 50000")).toBeTruthy();
    expect(region().textContent).toContain("Bars: all prints · feed ≥ 50,000 USDT");
    commit("0");
    await flush();
    expect(screen.getByText("feed filter: none")).toBeTruthy();
    expect(region().textContent).not.toMatch(/feed ≥/);
  });

  it("stops reading in heatmap mode and reads again on return", async () => {
    const { calls, read } = reads();
    render(<Host read={read} />);
    await flush();
    fireEvent.click(within(region()).getByRole("radio", { name: "Heatmap" }));
    await act(async () => void (await vi.advanceTimersByTimeAsync(2 * HOUR)));
    expect(calls).toHaveLength(1);
    fireEvent.click(within(region()).getByRole("radio", { name: "Bars" }));
    expect(within(region()).queryByRole("table")).toBeNull(); // old bars are never shown as fresh
    await flush();
    expect(calls).toHaveLength(2);
    expect(rows()).toHaveLength(5);
  });

  it("shows the coverage states of the one feed: pending while it loads, a retry when its read failed", async () => {
    const retry = vi.fn();
    const { read } = reads();
    const { rerender } = render(<Host coverage={null} read={read} onRetryCoverage={retry} />);
    await flush();
    expect(region().textContent).toContain("Waiting for recording coverage");
    rerender(<Host coverage={null} phase="failed" read={read} onRetryCoverage={retry} />);
    fireEvent.click(
      within(region()).getByRole("button", { name: "Retry loading Liquidation bars" }),
    );
    expect(retry).toHaveBeenCalledOnce();
  });

  it("leaves no timer and no pending read behind on unmount", async () => {
    const { calls, read } = reads();
    const { unmount } = render(<Host read={read} />);
    await flush();
    unmount();
    expect(calls[0]?.signal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("review folds", () => {
  const noop = (): void => undefined;
  const props = (over: Partial<Parameters<typeof LiquidationBarsPane>[0]> = {}) => ({
    symbol: "BTCUSDT",
    view: stories.viewOf(buildBars(SERVED_LONG, SERVED_SHORT, COVERAGE, HOUR)),
    coverage: { kind: "ok", coverage: COVERAGE } as const,
    settings: DEFAULT_LIQ_BAR_SETTINGS,
    feedMinNotionalUsd: null,
    onSettingsChange: noop,
    nowMs: NOW,
    ...over,
  });
  /** What a screen reader reads: the text without the `aria-hidden` parts. */
  const spoken = (el: Element): string => {
    const copy = el.cloneNode(true) as Element;
    copy.querySelectorAll('[aria-hidden="true"]').forEach((n) => n.remove());
    return copy.textContent;
  };

  it("never claims a filter the feed does not have: a setting alone states nothing", () => {
    render(
      <LiquidationBarsPane
        {...props({ settings: { ...DEFAULT_LIQ_BAR_SETTINGS, minNotionalUsd: "50000" } })}
      />,
    );
    expect(region().textContent).not.toMatch(/feed ≥|Showing prints/);
  });

  it("draws the side glyphs aria-hidden: the legend and the readout are read without a triangle", () => {
    render(<LiquidationBarsPane {...props({ crosshairMs: NOW - 30 * 60_000 })} />);
    const legend = within(region()).getByText(/above/);
    const readout = region().querySelector<HTMLElement>('p[aria-live="off"]') as HTMLElement;
    for (const el of [legend, readout]) {
      expect(el.textContent).toMatch(/[▲▼]/);
      expect(spoken(el)).not.toMatch(/[▲▼]/);
      expect(el.querySelectorAll('span[aria-hidden="true"]').length).toBeGreaterThan(0);
    }
    expect(spoken(legend)).toBe("Short liquidated  above · Long liquidated  below");
  });

  it("qualifies the readout of a bar that straddles the recorder's start, as its table row does", () => {
    const bars = buildBars(
      new Map([...SERVED_LONG, [HOUR * Math.floor(FIRST / HOUR), "1500.25"]]),
      SERVED_SHORT,
      COVERAGE,
      HOUR,
    );
    const open = HOUR * Math.floor(FIRST / HOUR);
    render(
      <LiquidationBarsPane {...props({ view: stories.viewOf(bars), crosshairMs: open + 1 })} />,
    );
    const readout = region().querySelector<HTMLElement>('p[aria-live="off"]') as HTMLElement;
    expect(spoken(readout)).toMatch(/^09:00 · Long liquidated {2}1,500\.25 USDT · /);
    expect(spoken(readout)).toMatch(/ · recorded from 09:14 UTC$/);
    // the same bar's table row says the same words
    expect(rows().map((r) => cells(r)[3])).toContain("recorded from 09:14 UTC");
  });

  it("leaves a fully recorded bar's readout without that qualifier", () => {
    render(<LiquidationBarsPane {...props({ crosshairMs: NOW - 30 * 60_000 })} />);
    const readout = region().querySelector<HTMLElement>('p[aria-live="off"]') as HTMLElement;
    expect(readout.textContent).not.toContain("recorded from");
  });

  it("resyncs the threshold field when the setting changes from outside", () => {
    const { rerender } = render(<LiquidationBarsPane {...props()} />);
    const field = () =>
      within(region()).getByRole("textbox", {
        name: "Minimum notional (USDT)",
      }) as HTMLInputElement;
    fireEvent.change(field(), { target: { value: "-1" } });
    fireEvent.blur(field());
    expect(field().getAttribute("aria-invalid")).toBe("true");
    rerender(
      <LiquidationBarsPane {...props({ settings: { mode: "bars", minNotionalUsd: "75000" } })} />,
    );
    expect(field().value).toBe("75000");
    expect(field().getAttribute("aria-invalid")).not.toBe("true");
  });

  it("has exactly one status node per pane, whatever the state", () => {
    const states = [
      stories.PartialBoundary,
      stories.Loading,
      stories.CoveragePending,
      stories.CoverageFailed,
      stories.Failed,
      stories.NotComputed,
      stories.Stale,
      stories.HeatmapPending,
      stories.BeforeCoverage,
    ];
    for (const story of states) {
      const { unmount } = render(story.render());
      expect(within(region()).getAllByRole("status")).toHaveLength(1);
      unmount();
    }
  });

  it("says a loading, stale and failed pane once, in its status node", () => {
    const { unmount } = render(stories.Loading.render());
    expect(within(region()).getByRole("status").textContent).toBe("Loading liquidation bars…");
    unmount();
    const stale = render(stories.Stale.render());
    expect(within(region()).getByRole("status").textContent).toBe("Stale · last 11:25:00 UTC");
    stale.unmount();
    render(stories.Failed.render());
    expect(within(region()).getByRole("status").textContent).toBe("Couldn't load liquidation bars");
  });
});

describe("accessibility", () => {
  it.each(
    Object.entries(stories).filter(([, s]) => typeof s === "object" && s !== null && "render" in s),
  )(
    "story %s has no serious or critical axe violation",
    async (_name, story) => {
      render((story as { render: () => JSX.Element }).render());
      expect(await serious()).toEqual([]);
    },
    30_000,
  );
});
