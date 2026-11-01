import { createRequire } from "node:module";
import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import {
  ChartDataTable,
  WINDOW_BUFFER,
  defaultClipboard,
} from "../../../src/chart/a11y/ChartDataTable";
import type { ChartTableSeries } from "../../../src/chart/a11y/series";
import { makeSeries } from "./fixture";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

interface Extra {
  initialBar?: number;
  levels?: number;
  series?: ChartTableSeries;
  onExit?: () => void;
}

function setup(bars = 50, extra: Extra = {}) {
  const say = vi.fn<(text: string) => void>();
  const writeClipboard = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
  const series = extra.series ?? makeSeries({ bars, levels: extra.levels ?? 3 });
  const ui = (s: ChartTableSeries): JSX.Element => (
    <ChartDataTable
      series={s}
      title="BTCUSDT 1m"
      focusOnOpen
      say={say}
      writeClipboard={writeClipboard}
      {...(extra.initialBar === undefined ? {} : { initialBar: extra.initialBar })}
      {...(extra.onExit === undefined ? {} : { onExit: extra.onExit })}
    />
  );
  const view = render(ui(series));
  return {
    say,
    writeClipboard,
    series,
    ...view,
    update: (s: ChartTableSeries) => view.rerender(ui(s)),
  };
}

const focused = (): HTMLElement => document.activeElement as HTMLElement;
const rowOf = (el: Element): HTMLElement => el.closest("tr") as HTMLElement;
const key = (k: string, init: KeyboardEventInit = {}): void => {
  fireEvent.keyDown(focused(), { key: k, ...init });
};
const selectedRows = (): HTMLElement[] =>
  screen.getAllByRole("row").filter((r) => r.getAttribute("aria-selected") === "true");
const levelRows = (): HTMLElement[] => screen.queryAllByRole("row", { name: /^Level \d+ of \d+/ });

describe("SCR-045 grid semantics", () => {
  it("is a grid named by its caption with column and row headers", () => {
    setup(5);
    const grid = screen.getByRole("grid", { name: "BTCUSDT 1m — 5 bars loaded" });
    expect(grid).toHaveAttribute("aria-rowcount", "6");
    const headers = within(grid)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "levels",
      "time",
      "open",
      "high",
      "low",
      "close",
      "volume",
      "delta",
      "CVD",
    ]);
    expect(
      within(grid).getByRole("rowheader", { name: /2026-10-20 13:00:00 UTC/ }),
    ).toBeInTheDocument();
  });

  it("opens on the initial bar with focus on its time cell and says where it is", () => {
    const { say } = setup(50, { initialBar: 20 });
    expect(focused()).toHaveAccessibleName(/13:20:00 UTC/);
    expect(rowOf(focused())).toHaveAttribute("aria-current", "true");
    expect(say).toHaveBeenCalledWith("Data table, row 21 of 50");
  });

  it("shows every canvas datum of a bar: OHLC, volume, delta and CVD", () => {
    setup(3, { initialBar: 0 });
    const cells = within(rowOf(focused()))
      .getAllByRole("gridcell")
      .map((c) => c.textContent);
    expect(cells.slice(1)).toEqual([
      "64,010.0",
      "64,011.0",
      "64,009.5",
      "64,010.5",
      "1.500",
      "+0.100",
      "+0.100",
    ]);
  });

  it("says 'not available' without footprint", () => {
    setup(2, { levels: 0, initialBar: 0 });
    expect(within(rowOf(focused())).getAllByText("—").length).toBeGreaterThan(1);
    expect(within(rowOf(focused())).getByText("No footprint for this bar")).toBeInTheDocument();
  });

  it("has no serious or critical axe violation, collapsed and expanded", async () => {
    // axe probes icon ligatures on a canvas jsdom lacks; without one it skips the probe.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const { container } = setup(10, { initialBar: 2 });
    const check = async (): Promise<void> => {
      const res = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
      const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => v.id)).toEqual([]);
    };
    await check();
    key("Enter");
    await check();
  });
});

describe("Gherkin 5: windowed at 100 000 bars", () => {
  it("draws only the window around the cursor, with absolute row indices", () => {
    setup(100_000);
    const grid = screen.getByRole("grid");
    expect(grid).toHaveAttribute("aria-rowcount", "100001");
    const drawn = within(grid)
      .getAllByRole("row")
      .filter((r) => r.closest("tbody") !== null && r.hasAttribute("aria-rowindex"));
    expect(drawn.length).toBeLessThanOrEqual(2 * WINDOW_BUFFER + 1);
    expect(rowOf(focused())).toHaveAttribute("aria-rowindex", "100001");
  });

  it("Ctrl+Home then ↓ reaches the oldest bar through the window, focus never lost", () => {
    setup(100_000);
    act(() => key("Home", { ctrlKey: true }));
    expect(focused()).toHaveTextContent("levels"); // the APG grid's first cell: the header row's
    act(() => key("ArrowDown"));
    expect(rowOf(focused())).toHaveAttribute("aria-rowindex", "2");
    act(() => key("End", { ctrlKey: true }));
    expect(rowOf(focused())).toHaveAttribute("aria-rowindex", "100001");
  });
});

describe("keyboard (E11-D04 §17.1)", () => {
  it("arrows move by row and cell, Home/End within the row, PageUp a page", () => {
    setup(50, { initialBar: 30 });
    key("ArrowUp");
    expect(focused()).toHaveAccessibleName(/13:29:00 UTC/);
    key("End");
    expect(focused()).toHaveTextContent("+3.000");
    key("ArrowLeft");
    expect(focused()).toHaveTextContent("+0.100");
    key("Home");
    expect(within(focused()).getByRole("button", { name: "Expand 3 levels" })).toBeInTheDocument();
    key("ArrowRight");
    expect(focused()).toHaveAccessibleName(/13:29:00 UTC/);
    key("PageUp");
    expect(rowOf(focused())).toHaveAttribute("aria-rowindex", String(30 - 10 + 1));
  });

  it("Enter expands the levels as grid rows under the bar; arrows walk them; Esc collapses", () => {
    const { say } = setup(10, { initialBar: 4 });
    key("Enter");
    expect(say).toHaveBeenCalledWith("Expanded, 3 levels");
    expect(screen.getByRole("grid")).toHaveAttribute("aria-rowcount", String(1 + 10 + 3));
    const rows = levelRows();
    expect(rows).toHaveLength(3);
    const trigger = screen.getByRole("button", { name: "Collapse 3 levels" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger.getAttribute("aria-controls")?.split(" ")).toEqual(rows.map((r) => r.id));
    expect(rows[0]).toHaveAccessibleName(
      /^Level 1 of 3, bar 2026-10-20 13:04:00 UTC price 64,012.5 bid 0.100 ask 0.500 delta \+0.400 imbalance Ask-stacked$/,
    );
    // Focus lands on the first level's price cell, a row header the bar's time describes.
    expect(focused()).toHaveAttribute("scope", "row");
    expect(focused()).toHaveAccessibleName("price 64,012.5");
    expect(focused()).toHaveAccessibleDescription("Level 1 of 3, bar 2026-10-20 13:04:00 UTC");
    key("ArrowDown");
    expect(focused()).toHaveAccessibleName("price 64,012.0");
    key("ArrowRight");
    expect(focused()).toHaveTextContent("bid 0.100");
    key("ArrowDown");
    expect(focused()).toHaveTextContent("bid 0.400");
    key("Escape");
    expect(say).toHaveBeenLastCalledWith("Collapsed");
    expect(levelRows()).toHaveLength(0);
    expect(focused()).toHaveAccessibleName(/13:04:00 UTC/);
  });

  it("windowing counts the level rows: indices shift below the open bar, Ctrl+End reaches the end", () => {
    setup(100_000, { initialBar: 50_000 });
    act(() => key("Enter"));
    expect(screen.getByRole("grid")).toHaveAttribute("aria-rowcount", String(1 + 100_000 + 3));
    expect(rowOf(focused())).toHaveAttribute("aria-rowindex", "50003");
    act(() => key("ArrowDown"));
    act(() => key("ArrowDown"));
    act(() => key("ArrowDown"));
    expect(rowOf(focused())).toHaveAttribute("data-bar", "50001");
    expect(rowOf(focused())).toHaveAttribute("aria-rowindex", "50006");
    act(() => key("End", { ctrlKey: true }));
    expect(rowOf(focused())).toHaveAttribute("aria-rowindex", "100004");
    expect(rowOf(focused())).toHaveAttribute("data-bar", "99999");
  });

  it("collapse returns focus to the column it opened from (the expander cell)", () => {
    setup(10, { initialBar: 4 });
    key("Home");
    key("Enter");
    expect(levelRows()).toHaveLength(3);
    key("Escape");
    expect(within(focused()).getByRole("button", { name: "Expand 3 levels" })).toBeInTheDocument();
    expect(rowOf(focused())).toHaveAttribute("data-bar", "4");
  });

  it("→ on the time cell expands, ← on a level's price cell or the open bar's time cell collapses", () => {
    const { say } = setup(10, { initialBar: 4 });
    key("ArrowRight");
    expect(say).toHaveBeenLastCalledWith("Expanded, 3 levels");
    expect(focused()).toHaveAccessibleName("price 64,012.5");
    key("ArrowLeft");
    expect(say).toHaveBeenLastCalledWith("Collapsed");
    expect(focused()).toHaveAccessibleName(/13:04:00 UTC/);
    key("Enter");
    key("ArrowUp");
    expect(focused()).toHaveAccessibleName(/13:04:00 UTC/);
    key("ArrowLeft");
    expect(levelRows()).toHaveLength(0);
    expect(focused()).toHaveAccessibleName(/13:04:00 UTC/);
  });

  it("→ on the time cell of a bar without levels moves to the next cell", () => {
    setup(5, { levels: 0, initialBar: 1 });
    key("ArrowRight");
    expect(focused()).toHaveTextContent("64,010.5"); // bar 1's open
  });

  it("Esc on another bar's row collapses the open bar without moving focus", () => {
    const { say } = setup(10, { initialBar: 4 });
    key("Enter");
    key("ArrowUp"); // the open bar's row
    key("ArrowUp"); // the bar above it
    expect(focused()).toHaveAccessibleName(/13:03:00 UTC/);
    key("Escape");
    expect(say).toHaveBeenLastCalledWith("Collapsed");
    expect(levelRows()).toHaveLength(0);
    expect(focused()).toHaveAccessibleName(/13:03:00 UTC/);
  });

  it("Esc with nothing selected or open returns to the chart", () => {
    const onExit = vi.fn();
    setup(10, { initialBar: 4, onExit });
    key(" ");
    key("Escape"); // clears the selection
    expect(onExit).not.toHaveBeenCalled();
    key("Enter");
    key("Escape"); // collapses
    expect(onExit).not.toHaveBeenCalled();
    key("Escape");
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it("the expander button toggles too; a second click collapses", () => {
    setup(5, { initialBar: 1 });
    fireEvent.click(screen.getAllByRole("button", { name: "Expand 3 levels" })[1] as HTMLElement);
    expect(levelRows()).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Collapse 3 levels" }));
    expect(levelRows()).toHaveLength(0);
  });

  it("Space selects, Shift+↓ extends, Esc clears", () => {
    const { say } = setup(10, { initialBar: 2 });
    key(" ");
    expect(rowOf(focused())).toHaveAttribute("aria-selected", "true");
    expect(say).toHaveBeenLastCalledWith("Selected, 1 row");
    act(() => key("ArrowDown", { shiftKey: true }));
    act(() => key("ArrowDown", { shiftKey: true }));
    expect(say).toHaveBeenLastCalledWith("Selected, 3 rows");
    expect(selectedRows()).toHaveLength(3);
    key("Escape");
    expect(say).toHaveBeenLastCalledWith("Deselected");
    expect(selectedRows()).toHaveLength(0);
    key(" ");
    key(" ");
    expect(say).toHaveBeenLastCalledWith("Deselected");
  });

  it("Shift+↓ extends from the cursor row after plain moves, not from where the table opened", () => {
    const { say } = setup(10); // opens on the latest bar, 9
    key("ArrowUp");
    key("ArrowUp");
    key("ArrowUp");
    expect(focused()).toHaveAccessibleName(/13:06:00 UTC/);
    act(() => key("ArrowDown", { shiftKey: true }));
    expect(say).toHaveBeenLastCalledWith("Selected, 2 rows");
    expect(selectedRows().map((r) => r.getAttribute("data-bar"))).toEqual(["6", "7"]);
  });

  it("Ctrl+A selects every loaded bar", () => {
    const { say } = setup(10, { initialBar: 2 });
    key("a", { ctrlKey: true });
    expect(say).toHaveBeenLastCalledWith("Selected, 10 rows");
    expect(selectedRows()).toHaveLength(10);
  });

  it("Ctrl+C copies the selection as TSV through the injected writer and says so", async () => {
    const { say, writeClipboard } = setup(10, { initialBar: 2 });
    key(" ");
    act(() => key("ArrowDown", { shiftKey: true }));
    await act(async () => key("c", { ctrlKey: true }));
    const text = writeClipboard.mock.calls[0]?.[0] ?? "";
    expect(text.split("\n")[0]).toBe("time\topen\thigh\tlow\tclose\tvolume\tdelta\tCVD");
    expect(text.split("\n")).toHaveLength(4);
    expect(say).toHaveBeenLastCalledWith("Copied 2 rows, 8 columns as TSV");
  });

  it("Ctrl+C with nothing selected copies the cursor row; a refused clipboard says 'Copy failed'", async () => {
    const { say, writeClipboard } = setup(10, { initialBar: 5 });
    writeClipboard.mockRejectedValueOnce(new Error("denied"));
    say.mockClear();
    await act(async () => key("c", { ctrlKey: true }));
    expect(writeClipboard.mock.calls[0]?.[0]).toContain("2026-10-20T13:05:00Z");
    expect(say).toHaveBeenCalledTimes(1);
    expect(say).toHaveBeenCalledWith("Copy failed");
  });
});

describe("the default clipboard writer (security look, Low)", () => {
  it("rejects instead of throwing when the Clipboard API is absent", async () => {
    const saved = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    try {
      await expect(defaultClipboard("x")).rejects.toThrow("clipboard unavailable");
    } finally {
      if (saved) Object.defineProperty(navigator, "clipboard", saved);
      else Reflect.deleteProperty(navigator, "clipboard");
    }
  });
});

describe("robustness (code lens r1 m5, m6)", () => {
  it("a tick finer than the price digits reads 'not available' instead of crashing; copy fails aloud", async () => {
    const series = { ...makeSeries({ bars: 3 }), priceDecimals: 0 }; // tick 0.5 at 0 decimals
    const { say, writeClipboard } = setup(3, { series, initialBar: 1 });
    const cells = within(rowOf(focused()))
      .getAllByRole("gridcell")
      .map((c) => c.textContent);
    expect(cells.slice(1, 5)).toEqual(["—", "—", "—", "—"]);
    expect(focused()).toHaveAccessibleName(/13:01:00 UTC/);
    await act(async () => key("c", { ctrlKey: true }));
    expect(writeClipboard).not.toHaveBeenCalled();
    expect(say).toHaveBeenLastCalledWith("Copy failed");
  });

  it("a focus request whose row never drew does not pull focus on a later render", () => {
    const { say, update } = setup(0, { levels: 0 });
    const elsewhere = document.createElement("button");
    document.body.append(elsewhere);
    elsewhere.focus();
    update(makeSeries({ bars: 5, levels: 0 }));
    expect(elsewhere).toHaveFocus();
    expect(say).not.toHaveBeenCalled();
    elsewhere.remove();
  });

  it("a series that shrinks clamps the cursor and drops the open bar and stale selections", async () => {
    const { update, writeClipboard } = setup(50, { initialBar: 40 });
    key(" ");
    key("Enter");
    update(makeSeries({ bars: 10 }));
    expect(levelRows()).toHaveLength(0);
    expect(selectedRows()).toHaveLength(0);
    expect(screen.getByRole("grid")).toHaveAttribute("aria-rowcount", "11");
    expect(
      screen.getAllByRole("row").filter((r) => r.getAttribute("aria-current") === "true"),
    ).toHaveLength(1);
    expect(
      screen.getAllByRole("row").find((r) => r.getAttribute("aria-current") === "true"),
    ).toHaveAttribute("data-bar", "9");
    const row = screen.getAllByRole("row").find((r) => r.getAttribute("data-bar") === "9");
    act(() => row?.querySelector<HTMLElement>("th")?.focus());
    await act(async () => key("c", { ctrlKey: true }));
    // The stale selection (bar 40) is gone: the copy is the cursor row.
    expect(writeClipboard.mock.calls[0]?.[0].split("\n")).toHaveLength(3);
    expect(writeClipboard.mock.calls[0]?.[0]).toContain("2026-10-20T13:09:00Z");
  });
});
