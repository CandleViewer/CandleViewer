import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { LadderGrid, type LadderRow } from "../../../src/chart/a11y/LadderGrid";
import { DEFAULT_WINDOW_ROWS } from "../../../src/chart/a11y/useCompositeGrid";
import { announceFill, fillSentence } from "../../../src/chart/a11y/fillAnnouncer";
import { TARGET_MIN_PX, TARGET_SIZE_EXCEPTIONS } from "../../../src/chart/a11y/targetSize";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

/** `n` rows from `top` down, one tick apart; asks above the middle, bids below. */
function book(n: number, top = 64100, size = "12"): LadderRow[] {
  const mid = top - Math.floor(n / 2);
  return Array.from({ length: n }, (_, i) => {
    const price = top - i;
    const side = price > mid ? "ask" : price < mid ? "bid" : "spread";
    return {
      key: String(price),
      price: String(price),
      bid: side === "bid" ? size : "0",
      ask: side === "ask" ? size : "0",
      side,
    } as const;
  });
}

const focused = (): HTMLElement => document.activeElement as HTMLElement;
const press = (key: string, init: KeyboardEventInit = {}): void => {
  fireEvent.keyDown(focused(), { key, ...init });
};
const tabbables = (root: HTMLElement): HTMLElement[] =>
  [...root.querySelectorAll<HTMLElement>("button, [tabindex]")].filter((el) => el.tabIndex >= 0);

beforeEach(() => clearAnnouncements());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  clearAnnouncements();
});

describe("Gherkin 1: crossing the ladder costs a few keystrokes, not two hundred", () => {
  it("200 rows are one Tab stop; arrows, PageUp/PageDown and Home/End move within", () => {
    const { container } = render(
      <>
        <button type="button">before</button>
        <LadderGrid symbol="BTCUSDT" rows={book(200)} initialRow={90} />
        <button type="button">after</button>
      </>,
    );
    const grid = screen.getByRole("grid", { name: "BTCUSDT order book ladder" });
    expect(grid).toHaveAttribute("aria-rowcount", "200");
    const stops = tabbables(grid);
    expect(stops).toHaveLength(1);
    expect(
      tabbables(container).map((el) => el.getAttribute("aria-label") ?? el.textContent),
    ).toEqual(["before", stops[0]?.getAttribute("aria-label"), "after"]);
    act(() => stops[0]?.focus());
    expect(focused()).toHaveAccessibleName(/^64,010, bid 0, ask 12, ask side$/);
    press("ArrowUp");
    expect(focused()).toHaveAccessibleName(/^64,011,/);
    press("PageDown");
    expect(focused()).toHaveAccessibleName(/^64,001,/);
    press("End");
    expect(focused()).toHaveAccessibleName(/^63,901,/);
    expect(focused().closest("[role='row']")).toHaveAttribute("aria-rowindex", "200");
    press("Home");
    expect(focused()).toHaveAccessibleName(/^64,100,/);
    press("End", { ctrlKey: true });
    expect(focused()).toHaveAccessibleName(/^63,901,/);
    press("Home", { ctrlKey: true });
    expect(focused()).toHaveAccessibleName(/^64,100,/);
    expect(tabbables(grid)).toEqual([focused()]);
  });

  it("a full-depth ladder materialises only the window (a11y_surrogate_nodes ceiling)", () => {
    render(<LadderGrid symbol="BTCUSDT" rows={book(1000)} initialRow={500} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBeLessThanOrEqual(DEFAULT_WINDOW_ROWS);
    const cell = screen.getAllByRole("gridcell").find((c) => c.tabIndex === 0);
    act(() => cell?.focus());
    for (let i = 0; i < 60; i++) press("PageDown");
    expect(screen.getAllByRole("row").length).toBeLessThanOrEqual(DEFAULT_WINDOW_ROWS);
    expect(focused().closest("[role='row']")).toHaveAttribute("aria-rowindex", "1000");
  });

  it("Enter, Ctrl+Enter and Ctrl+Delete are not the grid's: they reach the host's seam, nothing moves", () => {
    const onRowKeyDown = vi.fn();
    render(
      <LadderGrid symbol="BTCUSDT" rows={book(20)} initialRow={12} onRowKeyDown={onRowKeyDown} />,
    );
    const cell = screen.getAllByRole("gridcell").find((c) => c.tabIndex === 0);
    act(() => cell?.focus());
    press("Enter");
    press("Enter", { ctrlKey: true });
    press("Delete", { ctrlKey: true });
    expect(onRowKeyDown).toHaveBeenCalledTimes(3);
    expect(onRowKeyDown.mock.calls.map((c) => (c[0] as LadderRow).price)).toEqual([
      "64088",
      "64088",
      "64088",
    ]);
    expect(focused()).toBe(cell);
  });

  it("a key the host handled (preventDefault) does not also move the stop", () => {
    render(
      <LadderGrid
        symbol="BTCUSDT"
        rows={book(20)}
        initialRow={5}
        onRowKeyDown={(_, event) => event.key === "ArrowDown" && event.preventDefault()}
      />,
    );
    const cell = screen.getAllByRole("gridcell").find((c) => c.tabIndex === 0);
    act(() => cell?.focus());
    press("ArrowDown");
    expect(focused()).toBe(cell);
  });
});

describe("churn under focus (BQ-07: silent, in place, never stolen)", () => {
  it("the book shifts: focus stays on its price and its name updates without an announcement", () => {
    const { rerender } = render(
      <>
        <ShellAnnouncer />
        <LadderGrid symbol="BTCUSDT" rows={book(200)} initialRow={90} />
      </>,
    );
    const cell = screen.getAllByRole("gridcell").find((c) => c.tabIndex === 0) as HTMLElement;
    act(() => cell.focus());
    rerender(
      <>
        <ShellAnnouncer />
        <LadderGrid symbol="BTCUSDT" rows={book(200, 64105, "30")} initialRow={90} />
      </>,
    );
    expect(focused()).toBe(cell);
    expect(focused()).toHaveAccessibleName(/^64,010, bid 0, ask 30,/);
    expect(focused().closest("[role='row']")).toHaveAttribute("aria-rowindex", "96");
    for (const region of document.querySelectorAll("[aria-live]"))
      expect(region.textContent).toBe("");
  });

  it("the focused price leaves the book: focus goes to the nearest row, never to the page", () => {
    const { rerender } = render(<LadderGrid symbol="BTCUSDT" rows={book(50)} initialRow={10} />);
    act(() =>
      screen
        .getAllByRole("gridcell")
        .find((c) => c.tabIndex === 0)
        ?.focus(),
    );
    rerender(<LadderGrid symbol="BTCUSDT" rows={book(50, 63000)} initialRow={10} />);
    expect(focused()).toHaveAccessibleName(/^62,990,/);
  });

  it("focus outside the grid is never pulled back by churn", () => {
    const { rerender } = render(
      <>
        <button type="button">elsewhere</button>
        <LadderGrid symbol="BTCUSDT" rows={book(50)} initialRow={10} />
      </>,
    );
    act(() => screen.getByRole("button", { name: "elsewhere" }).focus());
    rerender(
      <>
        <button type="button">elsewhere</button>
        <LadderGrid symbol="BTCUSDT" rows={book(50, 63000)} initialRow={10} />
      </>,
    );
    expect(focused()).toHaveAccessibleName("elsewhere");
  });

  it("a pointer or AT focus on another row moves the stop there", () => {
    render(<LadderGrid symbol="BTCUSDT" rows={book(20)} initialRow={0} />);
    const other = screen.getAllByRole("gridcell")[7] as HTMLElement;
    act(() => other.focus());
    expect(other.tabIndex).toBe(0);
    expect(screen.getAllByRole("gridcell").filter((c) => c.tabIndex === 0)).toEqual([other]);
  });
});

describe("Gherkin 6: a fill does not hijack the keyboard", () => {
  it("the fill is said assertively and focus stays on the current row", () => {
    vi.useFakeTimers();
    render(
      <>
        <ShellAnnouncer />
        <LadderGrid symbol="BTCUSDT" rows={book(200)} initialRow={90} />
      </>,
    );
    const cell = screen.getAllByRole("gridcell").find((c) => c.tabIndex === 0) as HTMLElement;
    act(() => cell.focus());
    press("ArrowDown");
    const row = focused();
    act(() =>
      announceFill({ side: "buy", qty: "0.1", symbol: "BTCUSDT", price: "64009", account: "Main" }),
    );
    expect(focused()).toBe(row);
    const assertive = document.querySelector("[aria-live='assertive']");
    expect(assertive?.textContent).toBe("Filled: bought 0.1 BTCUSDT at 64,009, Main");
  });

  it("through a surface's writer the fill is its alert (pending ambient values drop)", () => {
    const alert = vi.fn();
    announceFill(
      {
        side: "sell",
        qty: "2",
        symbol: "BTCUSDT",
        price: "64010.5",
        account: "Hedge",
        partial: true,
      },
      { alert },
    );
    expect(alert).toHaveBeenCalledWith("Filled: sold 2 BTCUSDT at 64,010.5, Hedge, partial");
    const say = vi.fn();
    announceFill({ side: "buy", qty: "1", symbol: "X", price: "1", account: "A" }, undefined, say);
    expect(say).toHaveBeenCalledWith(
      "assertive",
      fillSentence({ side: "buy", qty: "1", symbol: "X", price: "1", account: "A" }),
    );
  });
});

describe("Gherkin 5: target size is accounted for", () => {
  it("ladder rows are at least size.target.min (24 CSS px) at default zoom", () => {
    const tokens = JSON.parse(
      readFileSync(
        resolve(import.meta.dirname, "../../../../../packages/ui/tokens/primitives.tokens.json"),
        "utf8",
      ),
    ) as Record<string, { $value: string }>;
    expect(Number(tokens["size.target.min"]?.$value)).toBe(TARGET_MIN_PX);
    expect(TARGET_MIN_PX).toBeGreaterThanOrEqual(24);
    const css = readFileSync(
      resolve(import.meta.dirname, "../../../src/chart/a11y/orderflowMarks.css"),
      "utf8",
    );
    const rule = /\.cv-of-ladder__cell \{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(rule).toMatch(/min-block-size: var\(--size-target-min\)/);
    expect(rule).toMatch(/min-inline-size: var\(--size-target-min\)/);
    render(<LadderGrid symbol="BTCUSDT" rows={book(5)} />);
    for (const cell of screen.getAllByRole("gridcell"))
      expect(cell).toHaveClass("cv-of-ladder__cell");
  });

  it("the footprint zoom-out exception is recorded with SCR-045 as the alternative", () => {
    expect(TARGET_SIZE_EXCEPTIONS).toEqual([
      expect.objectContaining({
        sc: "2.5.8",
        basis: "essential",
        component: "CMP-109",
        alternative: "SCR-045",
      }),
    ]);
  });
});

describe("the ladder surrogate's tree", () => {
  it("has a persistent text legend and no axe violations", async () => {
    // jsdom has no canvas; axe's icon-ligature probe then reads null, as in a canvas-less renderer.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const { container } = render(<LadderGrid symbol="BTCUSDT" rows={book(30)} initialRow={15} />);
    expect(within(container).getByRole("list", { name: "Book sides" })).toBeInTheDocument();
    const { violations } = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });

  it("unmounts cleanly: no focus restore or write after teardown", () => {
    const { unmount } = render(<LadderGrid symbol="BTCUSDT" rows={book(30)} initialRow={15} />);
    act(() =>
      screen
        .getAllByRole("gridcell")
        .find((c) => c.tabIndex === 0)
        ?.focus(),
    );
    unmount();
    expect(document.querySelectorAll("[role='grid']")).toHaveLength(0);
    expect(focused()).toBe(document.body);
  });
});
