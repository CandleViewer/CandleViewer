import { createRequire } from "node:module";
import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { ChartDataTable, WINDOW_BUFFER } from "../../../src/chart/a11y/ChartDataTable";
import { makeSeries } from "./fixture";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

function setup(bars = 50, extra: { initialBar?: number; levels?: number } = {}) {
  const say = vi.fn<(text: string) => void>();
  const writeClipboard = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
  const series = makeSeries({ bars, levels: extra.levels ?? 3 });
  const view = render(
    <ChartDataTable
      series={series}
      title="BTCUSDT 1m"
      focusOnOpen
      say={say}
      writeClipboard={writeClipboard}
      {...(extra.initialBar === undefined ? {} : { initialBar: extra.initialBar })}
    />,
  );
  return { say, writeClipboard, series, ...view };
}

const focused = (): HTMLElement => document.activeElement as HTMLElement;
const rowOf = (el: Element): HTMLElement => el.closest("tr") as HTMLElement;
const key = (k: string, init: KeyboardEventInit = {}): void => {
  fireEvent.keyDown(focused(), { key: k, ...init });
};

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
    key("ArrowRight");
    expect(focused()).toHaveTextContent("64,010.5");
    key("End");
    expect(focused()).toHaveTextContent("+3.000");
    key("Home");
    expect(within(focused()).getByRole("button", { name: "Expand 3 levels" })).toBeInTheDocument();
    key("PageUp");
    expect(rowOf(focused())).toHaveAttribute("aria-rowindex", String(30 - 10 + 1));
  });

  it("Enter expands the bar's footprint levels, Esc collapses back to the bar", () => {
    const { say } = setup(10, { initialBar: 4 });
    key("Enter");
    expect(say).toHaveBeenCalledWith("Expanded, 3 levels");
    expect(screen.getByRole("button", { name: "Collapse 3 levels" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    const levels = screen.getByRole("table", { name: /3 price levels, 64,012.5 to 64,011.5/ });
    expect(
      within(levels)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["price", "bid", "ask", "delta", "imbalance"]);
    expect(
      within(levels).getByRole("row", { name: /64,012.5 0.100 0.500 \+0.400 Ask-stacked/ }),
    ).toBeInTheDocument();
    expect(focused().contains(levels)).toBe(true); // the merged cell that holds the levels
    key("Escape");
    expect(say).toHaveBeenLastCalledWith("Collapsed");
    expect(screen.queryByRole("table", { name: /price levels/ })).toBeNull();
    expect(focused()).toHaveAccessibleName(/13:04:00 UTC/);
  });

  it("the expander button toggles too; a second Enter collapses", () => {
    setup(5, { initialBar: 1 });
    fireEvent.click(screen.getAllByRole("button", { name: "Expand 3 levels" })[1] as HTMLElement);
    expect(screen.getByRole("table", { name: /price levels/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Collapse 3 levels" }));
    expect(screen.queryByRole("table", { name: /price levels/ })).toBeNull();
  });

  it("Space selects, Shift+↓ extends, Esc clears", () => {
    const { say } = setup(10, { initialBar: 2 });
    key(" ");
    expect(rowOf(focused())).toHaveAttribute("aria-selected", "true");
    expect(say).toHaveBeenLastCalledWith("Selected, 1 row");
    act(() => key("ArrowDown", { shiftKey: true }));
    act(() => key("ArrowDown", { shiftKey: true }));
    expect(say).toHaveBeenLastCalledWith("Selected, 3 rows");
    expect(
      screen.getAllByRole("row").filter((r) => r.getAttribute("aria-selected") === "true"),
    ).toHaveLength(3);
    key("Escape");
    expect(say).toHaveBeenLastCalledWith("Deselected");
    expect(
      screen.getAllByRole("row").filter((r) => r.getAttribute("aria-selected") === "true"),
    ).toHaveLength(0);
    key(" ");
    key(" ");
    expect(say).toHaveBeenLastCalledWith("Deselected");
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

  it("Ctrl+C with nothing selected copies the cursor row; a refused clipboard says nothing", async () => {
    const { say, writeClipboard } = setup(10, { initialBar: 5 });
    writeClipboard.mockRejectedValueOnce(new Error("denied"));
    say.mockClear();
    await act(async () => key("c", { ctrlKey: true }));
    expect(writeClipboard.mock.calls[0]?.[0]).toContain("2026-10-20T13:05:00Z");
    expect(say).not.toHaveBeenCalled();
  });
});
