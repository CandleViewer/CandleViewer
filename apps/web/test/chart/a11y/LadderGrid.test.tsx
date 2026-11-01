import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { LadderGrid, type LadderRow } from "../../../src/chart/a11y/LadderGrid";
import { DEFAULT_WINDOW_ROWS } from "../../../src/chart/a11y/useCompositeGrid";
import {
  FILL_BATCH_CEILING,
  announceFill,
  announceFills,
  fillSentence,
  type FillEvent,
} from "../../../src/chart/a11y/fillAnnouncer";
import type { AccessibleAccount } from "../../../src/chart/a11y/readback";
import { TARGET_MIN_PX, TARGET_SIZE_EXCEPTIONS } from "../../../src/chart/a11y/targetSize";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { expectNoHueAlone } from "./noHueAlone";

const MINE: readonly AccessibleAccount[] = [
  { id: "acc-main", name: "Main", env: "live" },
  { id: "acc-hedge", name: "Hedge", env: "live" },
];

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

  it("the focused price leaves the book: focus goes to the nearest price, never to the page", () => {
    const { rerender } = render(<LadderGrid symbol="BTCUSDT" rows={book(50)} initialRow={10} />);
    act(() =>
      screen
        .getAllByRole("gridcell")
        .find((c) => c.tabIndex === 0)
        ?.focus(),
    );
    expect(focused()).toHaveAccessibleName(/^64,090,/);
    // Five new levels on top and 64,090 gone: the same index (10) would be 64,095, an unrelated price.
    const shifted = book(55, 64105).filter((r) => r.key !== "64090");
    rerender(<LadderGrid symbol="BTCUSDT" rows={shifted} initialRow={10} />);
    expect(focused()).toHaveAccessibleName(/^64,091,/);
    rerender(<LadderGrid symbol="BTCUSDT" rows={book(50, 63000)} initialRow={10} />);
    expect(focused()).toHaveAccessibleName(/^63,000,/);
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
  const fill = (over: Partial<FillEvent> = {}): FillEvent => ({
    side: "buy",
    qty: "0.1",
    symbol: "BTCUSDT",
    price: "64009",
    accountId: "acc-main",
    ...over,
  });

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
    act(() => announceFill(fill(), MINE));
    expect(focused()).toBe(row);
    const assertive = document.querySelector("[aria-live='assertive']");
    expect(assertive?.textContent).toBe("Filled: bought 0.1 BTCUSDT at 64,009, Main");
  });

  it("a partial fill leads with its state; through a surface's writer the fill is its alert", () => {
    const alert = vi.fn();
    announceFill(
      fill({ side: "sell", qty: "2", price: "64010.5", accountId: "acc-hedge", partial: true }),
      MINE,
      { alert },
    );
    expect(alert).toHaveBeenCalledWith("Partially filled: sold 2 BTCUSDT at 64,010.5, Hedge");
    const say = vi.fn();
    announceFill(fill(), MINE, undefined, say);
    expect(say).toHaveBeenCalledWith("assertive", fillSentence(fill(), MINE));
  });

  it("the account is named only through the accessible set; an id is never said (sec 4)", () => {
    const foreign = fill({ accountId: "8f14e45f-uid-123456" });
    expect(fillSentence(foreign, MINE)).toBe("Filled: bought 0.1 BTCUSDT at 64,009");
    expect(fillSentence(fill(), [])).toBe("Filled: bought 0.1 BTCUSDT at 64,009");
    const ambiguous: AccessibleAccount[] = [...MINE, { id: "x", name: "MAIN", env: "live" }];
    expect(fillSentence(fill(), ambiguous)).not.toMatch(/Main|MAIN|acc-main/);
    for (const f of [foreign, fill(), fill({ accountId: "acc-hedge" })])
      expect(fillSentence(f, MINE)).not.toContain(f.accountId);
  });

  it("a burst is bounded: 50 single fills leave one message, a batch is one utterance of 3 plus a count", () => {
    render(<ShellAnnouncer />);
    const burst = Array.from({ length: 50 }, (_, i) =>
      fill({ qty: String(i + 1), accountId: i % 2 === 0 ? "acc-main" : "acc-hedge" }),
    );
    act(() => burst.forEach((f) => announceFill(f, MINE)));
    const assertive = document.querySelector("[aria-live='assertive']") as HTMLElement;
    expect(assertive.children).toHaveLength(1);
    const say = vi.fn();
    announceFills(burst, MINE, undefined, say);
    expect(say).toHaveBeenCalledTimes(1);
    expect(FILL_BATCH_CEILING).toBe(3);
    expect(say).toHaveBeenCalledWith(
      "assertive",
      "Filled: bought 1 BTCUSDT at 64,009, Main. Filled: bought 2 BTCUSDT at 64,009, Hedge. " +
        "Filled: bought 3 BTCUSDT at 64,009, Main. 47 more fills",
    );
    announceFills([], MINE, undefined, say);
    expect(say).toHaveBeenCalledTimes(1);
  });
});

describe("faults, empty book and own state (lens r1)", () => {
  it("one faulty size degrades its row; the ladder still renders (code m4)", () => {
    const rows = book(10);
    rows[3] = { ...(rows[3] as LadderRow), bid: "-4" };
    rows[4] = { ...(rows[4] as LadderRow), ask: "1e3" };
    render(<LadderGrid symbol="BTCUSDT" rows={rows} />);
    expect(screen.getAllByRole("gridcell")).toHaveLength(10);
    const bad = screen.getByRole("gridcell", { name: /^64,097, bid not available, ask 12,/ });
    expect(bad.textContent).toContain("—");
    expect(
      screen.getByRole("gridcell", { name: /^64,096, bid 0, ask not available,/ }),
    ).toBeTruthy();
  });

  it("an empty book is a line of text, not a grid with no rows (a11y L-4)", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const { container } = render(<LadderGrid symbol="BTCUSDT" rows={[]} />);
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.getByRole("group", { name: "BTCUSDT order book ladder" })).toHaveTextContent(
      "No price levels in the book",
    );
    const { violations } = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });

  it("own orders and the position are drawn, not only named (a11y M-3)", () => {
    const base = book(3)[1] as LadderRow;
    const variants: Record<string, LadderRow> = {
      plain: base,
      own: { ...base, own: [{ side: "buy", qty: "0.1" }] },
      owns: {
        ...base,
        own: [
          { side: "buy", qty: "0.1" },
          { side: "sell", qty: "0.2" },
        ],
      },
      position: { ...base, position: { side: "long", qty: "0.5" } },
    };
    const cells: Record<string, Element> = {};
    for (const [name, row] of Object.entries(variants)) {
      const { container, unmount } = render(<LadderGrid symbol="BTCUSDT" rows={[row]} />);
      cells[name] = container.querySelector("[role='gridcell']")?.cloneNode(true) as Element;
      unmount();
    }
    expectNoHueAlone("ladder-row", cells);
    expect(cells["own"]?.textContent).toContain("Buy 0.1");
    expect(cells["owns"]?.textContent).toContain("2 orders");
    expect(cells["position"]?.textContent).toContain("Long 0.5");
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
        notApplicable: {
          spacing: expect.stringMatching(/abut/),
          equivalent: expect.stringMatching(/another screen/),
        },
        condition: expect.stringMatching(/default zoom is not asserted/),
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
