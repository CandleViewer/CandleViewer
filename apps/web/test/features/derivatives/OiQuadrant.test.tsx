// E24-S02 (#777) slice 2: the OI pane's mode and colouring toggles, the key row, the quadrant and delta table
// columns, the single polite status node, and axe over every story.
import { createRequire } from "node:module";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as stories from "../../../src/features/derivatives/oi/ui/OiQuadrant.stories";
import { OiPane } from "../../../src/features/derivatives/oi/ui/OiPane";
import { ConnectedOiPane } from "../../../src/features/derivatives/oi/ui/ConnectedOiPane";
import { INITIAL_OI_SNAPSHOT } from "../../../src/features/derivatives/oi/oiFeed";
import { buildOiBars } from "../../../src/features/derivatives/oi/quadrant/bars";
import {
  DELTA_SERIES,
  FIXTURE_BAR_MS,
  FIXTURE_ROWS,
  FIXTURE_T0,
  QUADRANT_SERIES,
} from "../../../src/features/derivatives/oi/quadrant/fixture";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

const model = () =>
  buildOiBars(DELTA_SERIES, QUADRANT_SERIES, FIXTURE_ROWS, FIXTURE_BAR_MS, "BTCUSDT");

afterEach(() => {
  vi.useRealTimers();
});

describe("OI quadrants", () => {
  it("names each quadrant with its count, and the unclassified apart (BQ-3)", () => {
    render(stories.QuadrantsOn.render());
    const key = screen.getByText(/^price · OI:/);
    expect(key.textContent).toContain("long build-up 1");
    expect(key.textContent).toContain("short covering 1");
    expect(key.textContent).toContain("short build-up 1");
    expect(key.textContent).toContain("long unwind 1");
    expect(key.textContent).toContain("1 unclassified (no OI sample)");
    expect(key.textContent).toMatch(/· 1 unclassified$/);
  });

  it("reads the crosshair quadrant in words only while colouring is on", () => {
    const { unmount } = render(stories.QuadrantsOn.render());
    expect(screen.getByText("long build-up (▲ price ▲ OI)")).toBeTruthy();
    unmount();
    render(stories.QuadrantsOff.render());
    expect(screen.getByText("Quadrants off")).toBeTruthy();
    expect(screen.queryByText("long build-up (▲ price ▲ OI)")).toBeNull();
  });

  it("puts the mode toggle in legend row 0, with no colouring button (F2), and reports it", () => {
    const seen: Record<string, unknown>[] = [];
    const on = (e: Event): void => {
      seen.push((e as CustomEvent<Record<string, unknown>>).detail);
    };
    window.addEventListener(THEME_ANALYTICS_EVENT, on);
    const onModeChange = vi.fn();
    render(
      <OiPane
        symbol="BTCUSDT"
        snapshot={INITIAL_OI_SNAPSHOT}
        onRetry={vi.fn()}
        bars={model()}
        mode="absolute"
        onModeChange={onModeChange}
      />,
    );
    expect(screen.queryByRole("button", { name: /colouring/i })).toBeNull();
    const abs = screen.getByRole("button", { name: /Absolute/ });
    const delta = screen.getByRole("button", { name: /Delta/ });
    expect(abs.getAttribute("aria-pressed")).toBe("true");
    expect(abs.textContent).toContain("✓"); // a marker beyond the fill
    fireEvent.click(delta);
    expect(onModeChange).toHaveBeenCalledWith("delta");
    // the host owns the mode: with no new prop the display does not move
    expect(abs.getAttribute("aria-pressed")).toBe("true");
    window.removeEventListener(THEME_ANALYTICS_EVENT, on);
    expect(seen.filter((d) => d["name"] === "oi_panel.metric_toggled")).toEqual([
      { name: "oi_panel.metric_toggled", mode: "delta", quadrant_colouring: true },
    ]);
  });

  it("keeps the mode toggle absent until the host gives both mode and onModeChange (BQ-1)", () => {
    const props = { symbol: "BTCUSDT", snapshot: INITIAL_OI_SNAPSHOT, onRetry: vi.fn() };
    const { rerender } = render(<OiPane {...props} bars={model()} />);
    const none = (): boolean =>
      screen.queryByRole("group", { name: "Open interest display" }) === null;
    expect(none()).toBe(true);
    rerender(<OiPane {...props} bars={model()} mode="delta" />); // no handler
    expect(none()).toBe(true);
    rerender(<OiPane {...props} bars={model()} onModeChange={vi.fn()} />); // no mode
    expect(none()).toBe(true);
    rerender(<OiPane {...props} bars={model()} mode="delta" onModeChange={vi.fn()} />);
    expect(none()).toBe(false);
  });

  it("treats another symbol's bars as absent: no key row, no rows, no announcement", () => {
    const props = {
      snapshot: { ...INITIAL_OI_SNAPSHOT, rows: [...FIXTURE_ROWS] },
      onRetry: vi.fn(),
    };
    const { container } = render(
      <OiPane symbol="ETHUSDT" {...props} bars={model()} defaultTableOpen />,
    );
    expect(screen.queryByText(/^price · OI:/)).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Quadrant" })).toBeNull();
    expect(container.querySelector(".cv-oi-pane__status")?.textContent).toBe("");
  });

  it("passes the served bars through the connected pane", () => {
    render(
      <ConnectedOiPane
        symbol="BTCUSDT"
        paneId="p1"
        barMs={FIXTURE_BAR_MS}
        fromMs={FIXTURE_T0}
        toMs={FIXTURE_T0 + 6 * FIXTURE_BAR_MS}
        bars={model()}
        instrumentBaseCoin="BTC"
      />,
    );
    expect(screen.getByText(/^price · OI:/)).toBeTruthy();
  });

  it("has no toggles or key row without the served bars (S01 unchanged)", () => {
    render(<OiPane symbol="BTCUSDT" snapshot={INITIAL_OI_SNAPSHOT} onRetry={vi.fn()} />);
    expect(screen.queryByRole("group", { name: "Open interest display" })).toBeNull();
  });

  it("puts the delta and the quadrant in words in the table, colouring on or off", () => {
    render(stories.QuadrantsOff.render());
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Δ per bar (qty)" })).toBeTruthy();
    expect(within(table).getByRole("columnheader", { name: "Quadrant" })).toBeTruthy();
    for (const w of ["long build-up", "short covering", "short build-up", "long unwind"]) {
      expect(within(table).getByText(w, { exact: false })).toBeTruthy(); // all four, in words
    }
    expect(within(table).getByText("+20")).toBeTruthy();
    expect(within(table).getByText("−8.25")).toBeTruthy();
    // the flat bar and the unsampled bar (absent from the feed's rows, so only the flat one has a row)
    expect(within(table).getAllByText("unclassified").length).toBe(1);
  });

  it("does not announce after a symbol switch that holds the old symbol's bars for a render", () => {
    const mk = (symbol: string, n: number) =>
      buildOiBars(
        {
          unit: "qty",
          points: Array.from({ length: n }, (_, i) => ({
            t: new Date(i * 600_000).toISOString(),
            v: null,
          })),
        },
        { unit: "enum", points: [] },
        [],
        FIXTURE_BAR_MS,
        symbol,
      );
    const snapshot = INITIAL_OI_SNAPSHOT;
    const onRetry = vi.fn();
    const { rerender } = render(
      <OiPane symbol="BTCUSDT" snapshot={snapshot} onRetry={onRetry} bars={mk("BTCUSDT", 1)} />,
    );
    const status = screen.getByRole("status");
    // the switch: the new symbol, still the old bars
    rerender(
      <OiPane symbol="ETHUSDT" snapshot={snapshot} onRetry={onRetry} bars={mk("BTCUSDT", 1)} />,
    );
    expect(status.textContent).toBe("");
    // the new symbol's bars land with a very different count: seeded, not announced
    rerender(
      <OiPane symbol="ETHUSDT" snapshot={snapshot} onRetry={onRetry} bars={mk("ETHUSDT", 9)} />,
    );
    expect(status.textContent).toBe("");
  });

  it("labels the delta with the instrument's base coin, falling back to qty", () => {
    const props = { symbol: "BTCUSDT", snapshot: INITIAL_OI_SNAPSHOT, onRetry: vi.fn() };
    const { rerender } = render(
      <OiPane {...props} bars={model()} instrumentBaseCoin="BTC" defaultTableOpen />,
    );
    expect(screen.getByRole("columnheader", { name: "Δ per bar (BTC)" })).toBeTruthy();
    rerender(<OiPane {...props} bars={model()} defaultTableOpen />);
    expect(screen.getByRole("columnheader", { name: "Δ per bar (qty)" })).toBeTruthy();
  });

  it("labels the readout's delta the same way", () => {
    render(
      <OiPane
        symbol="BTCUSDT"
        snapshot={INITIAL_OI_SNAPSHOT}
        onRetry={vi.fn()}
        bars={model()}
        instrumentBaseCoin="BTC"
        delta={{ value: "20", unit: "qty", quadrant: "long_buildup" }}
      />,
    );
    expect(screen.getByText("+20 BTC")).toBeTruthy();
  });

  it("joins a mid-bar row to its bar by alignment (A)", () => {
    const row = FIXTURE_ROWS[0];
    if (row === undefined) throw new Error("fixture");
    const mid = { ...row, tMs: row.tMs + 60_000, spanMs: 60_000 };
    render(
      <OiPane
        symbol="BTCUSDT"
        snapshot={{ ...INITIAL_OI_SNAPSHOT, rows: [mid] }}
        onRetry={vi.fn()}
        bars={model()}
        defaultTableOpen
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText("+20")).toBeTruthy();
    expect(within(table).getByText("long build-up", { exact: false })).toBeTruthy();
  });

  it("does not announce on the first load, announces a later material change (F1)", () => {
    const base = { symbol: "BTCUSDT", snapshot: INITIAL_OI_SNAPSHOT, onRetry: vi.fn() };
    const { rerender } = render(<OiPane {...base} />);
    const status = screen.getByRole("status");
    rerender(<OiPane {...base} bars={model()} />); // first bars, 2 unclassified
    expect(status.textContent).toBe("");
    const many = buildOiBars(
      {
        unit: "qty",
        points: [0, 1, 2, 3, 4].map((i) => ({ t: new Date(i * 600_000).toISOString(), v: null })),
      },
      { unit: "enum", points: [] },
      [],
      FIXTURE_BAR_MS,
      "BTCUSDT",
    );
    rerender(<OiPane {...base} bars={many} />); // 5 unclassified: +3
    expect(screen.getByRole("status")).toBe(status);
    expect(status.textContent).toBe("5 bars unclassified, no open-interest sample.");
    rerender(<OiPane {...base} bars={many} quadrantColouring={false} />); // counts hidden
    expect(status.textContent).toBe("");
  });

  it.each(Object.entries(stories).filter(([k]) => k !== "default"))(
    "has no serious axe violation in the %s story",
    { timeout: 30_000 },
    async (_name, story) => {
      const { unmount } = render((story as { render: () => JSX.Element }).render());
      const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
      expect(
        res.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
      ).toEqual([]);
      unmount();
    },
  );
});
