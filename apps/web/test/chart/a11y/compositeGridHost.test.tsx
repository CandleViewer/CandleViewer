import { createRequire } from "node:module";
import { useMemo } from "react";
import type { KeyboardEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { nearestDecimalKey } from "../../../src/chart/a11y/compositeGrid";
import {
  useCompositeGrid,
  type UseCompositeGridOptions,
} from "../../../src/chart/a11y/useCompositeGrid";
import {
  FILL_BATCH_CEILING,
  announceFill,
  announceFills,
  fillSentence,
  type FillEvent,
} from "../../../src/chart/a11y/fillAnnouncer";
import { FootprintCellContent } from "../../../src/chart/a11y/marks";
import { footprintCellSentence } from "../../../src/chart/a11y/orderflowFormat";
import type { AccessibleAccount } from "../../../src/chart/a11y/readback";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";

/**
 * A footprint-like host on the shared pieces (the re-homed LadderGrid tests, record 6563461150): price levels are
 * rows keyed by price, bars are columns, the stop follows its price through churn.
 */
interface Level {
  readonly price: string;
  readonly bid: string;
  readonly ask: string;
}

interface HostProps {
  readonly levels: readonly Level[];
  readonly cols?: number;
  readonly options?: Partial<UseCompositeGridOptions>;
  readonly onCellKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
  /** A text field in each focused-row cell of column 0 (a host's inline editor). */
  readonly editable?: boolean;
}

function Host({ levels, cols = 3, options, onCellKeyDown, editable }: HostProps): JSX.Element {
  const rowKeys = useMemo(() => levels.map((l) => l.price), [levels]);
  const grid = useCompositeGrid({
    rows: levels.length,
    cols,
    rowKeys,
    nearestRow: nearestDecimalKey,
    ...options,
  });
  const drawn: JSX.Element[] = [];
  for (let r = grid.window.first; r <= grid.window.last && r < levels.length; r++) {
    const level = levels[r];
    if (level === undefined) continue;
    const cell = { ...level, delta: "0", imbalance: null };
    drawn.push(
      <div key={level.price} {...grid.rowProps(r)}>
        {Array.from({ length: cols }, (_, c) => (
          <div
            key={c}
            {...grid.cellProps(r, c)}
            role="gridcell"
            tabIndex={grid.cellProps(r, c).tabIndex}
            aria-label={`bar ${c + 1}, ${footprintCellSentence(cell)}`}
            onKeyDown={onCellKeyDown}
          >
            <FootprintCellContent cell={cell} />
            {editable === true && c === 0 ? <input aria-label={`size at ${level.price}`} /> : null}
          </div>
        ))}
      </div>,
    );
  }
  return (
    <div {...grid.gridProps} aria-label="Footprint">
      {drawn}
    </div>
  );
}

/** `n` levels from `top` down, one tick apart. */
const levels = (n: number, top = 64100, size = "12"): Level[] =>
  Array.from({ length: n }, (_, i) => ({ price: String(top - i), bid: size, ask: size }));

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};
const expectNoSeriousAxe = async (el: Element): Promise<void> => {
  const res = await axe.run(el, { rules: { "color-contrast": { enabled: false } } });
  const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => v.id)).toEqual([]);
};

const focused = (): HTMLElement => document.activeElement as HTMLElement;
const press = (key: string, init: KeyboardEventInit = {}): void => {
  fireEvent.keyDown(focused(), { key, ...init });
};
const stop = (): HTMLElement =>
  screen.getAllByRole("gridcell").find((c) => c.tabIndex === 0) as HTMLElement;
const stops = (): HTMLElement[] => screen.getAllByRole("gridcell").filter((c) => c.tabIndex === 0);

beforeEach(() => clearAnnouncements());
afterEach(() => {
  vi.restoreAllMocks();
  clearAnnouncements();
});

describe("churn under focus (BQ-07: silent, in place, never stolen)", () => {
  it("new data keeps focus on its price, its name updates, nothing is announced", () => {
    const tree = (top: number, size: string): JSX.Element => (
      <>
        <ShellAnnouncer />
        <Host levels={levels(200, top, size)} options={{ initial: { row: 90 } }} />
      </>
    );
    const { rerender } = render(tree(64100, "12"));
    const cell = stop();
    act(() => cell.focus());
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,010, bid 12,/);
    rerender(tree(64105, "30"));
    expect(focused()).toBe(cell);
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,010, bid 30,/);
    expect(focused().closest("[role='row']")).toHaveAttribute("aria-rowindex", "96");
    expect(stops()).toEqual([focused()]);
    for (const region of document.querySelectorAll("[aria-live]"))
      expect(region.textContent).toBe("");
  });

  it("the focused price leaves: focus goes to the nearest price, never to the page", () => {
    const { rerender } = render(<Host levels={levels(50)} options={{ initial: { row: 10 } }} />);
    act(() => stop().focus());
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,090,/);
    // Five new levels on top and 64,090 gone: the same index (10) would be 64,095, an unrelated price.
    rerender(<Host levels={levels(55, 64105).filter((l) => l.price !== "64090")} />);
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,091,/);
    rerender(<Host levels={levels(50, 63000)} />);
    expect(focused()).toHaveAccessibleName(/^bar 1, 63,000,/);
  });

  it("focus outside the grid is never pulled back by churn", () => {
    const tree = (top: number): JSX.Element => (
      <>
        <button type="button">elsewhere</button>
        <Host levels={levels(50, top)} options={{ initial: { row: 10 } }} />
      </>
    );
    const { rerender } = render(tree(64100));
    act(() => stop().focus());
    act(() => screen.getByRole("button", { name: "elsewhere" }).focus());
    rerender(tree(63000));
    expect(focused()).toHaveAccessibleName("elsewhere");
    // Focus left the grid for the page itself; the row it was on then leaves: still not pulled back.
    act(() => stop().focus());
    act(() => focused().blur());
    rerender(tree(62000));
    expect(focused()).toBe(document.body);
  });

  it("a pointer or AT focus on another cell moves the stop there", () => {
    render(<Host levels={levels(20)} />);
    const other = screen.getAllByRole("gridcell")[7] as HTMLElement;
    act(() => other.focus());
    expect(other.tabIndex).toBe(0);
    expect(stops()).toEqual([other]);
  });

  it("a key the host handled (preventDefault) does not also move the stop", () => {
    const onCellKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
      if (event.key === "ArrowDown") event.preventDefault();
    };
    render(<Host levels={levels(20)} onCellKeyDown={onCellKeyDown} />);
    const cell = stop();
    act(() => cell.focus());
    press("ArrowDown");
    expect(focused()).toBe(cell);
    press("ArrowRight");
    expect(focused()).toHaveAccessibleName(/^bar 2, 64,100,/);
  });

  it("unmounts cleanly, and a fresh mount never takes focus by itself", () => {
    const { unmount } = render(<Host levels={levels(30)} options={{ initial: { row: 15 } }} />);
    act(() => stop().focus());
    unmount();
    expect(document.querySelectorAll("[role='grid']")).toHaveLength(0);
    expect(focused()).toBe(document.body);
    render(<Host levels={levels(30)} options={{ initial: { row: 15 } }} />);
    expect(focused()).toBe(document.body);
  });
});

describe("the host's layout is followed, not read once (record minor)", () => {
  it("a new pageRows, homeEnd or windowRows takes effect on the next key", () => {
    const data = levels(100); // the same rows throughout: only the layout changes
    const tree = (options: Partial<UseCompositeGridOptions>): JSX.Element => (
      <Host levels={data} options={{ page: "row", windowRows: 30, ...options }} />
    );
    const { rerender } = render(tree({ pageRows: 10, homeEnd: "row" }));
    act(() => stop().focus());
    press("PageDown");
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,090,/);
    rerender(tree({ pageRows: 2, homeEnd: "col", windowRows: 8 }));
    press("PageDown");
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,088,/);
    expect(screen.getAllByRole("row").length).toBeLessThanOrEqual(8);
    press("End");
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,001,/);
  });
});

describe("an editable control in a cell keeps its own keys (record minor)", () => {
  it("arrows, Home and End in a text field are neither prevented nor moved", () => {
    render(<Host levels={levels(10)} editable />);
    const field = screen.getByRole("textbox", { name: "size at 64100" });
    act(() => field.focus());
    for (const key of ["ArrowLeft", "ArrowRight", "ArrowDown", "Home", "End"])
      expect(fireEvent.keyDown(field, { key })).toBe(true);
    expect(focused()).toBe(field);
    act(() => stop().focus());
    expect(fireEvent.keyDown(focused(), { key: "ArrowDown" })).toBe(false);
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,099,/);
  });
});

describe("Gherkin 6: a fill does not hijack the keyboard", () => {
  const MINE: readonly AccessibleAccount[] = [
    { id: "acc-main", name: "Main", env: "live" },
    { id: "acc-hedge", name: "Hedge", env: "live" },
  ];
  const fill = (over: Partial<FillEvent> = {}): FillEvent => ({
    side: "buy",
    qty: "0.1",
    symbol: "BTCUSDT",
    price: "64009",
    accountId: "acc-main",
    ...over,
  });

  it("the fill is said in the assertive region and focus stays on the current cell", () => {
    render(
      <>
        <ShellAnnouncer />
        <Host levels={levels(200)} options={{ initial: { row: 90 } }} />
      </>,
    );
    act(() => stop().focus());
    press("ArrowDown");
    const cell = focused();
    act(() => announceFill(fill(), MINE));
    expect(focused()).toBe(cell);
    expect(document.querySelector("[aria-live='assertive']")?.textContent).toBe(
      "Filled: bought 0.1 BTCUSDT at 64,009, Main",
    );
    expect(document.querySelector("[aria-live='polite']")?.textContent ?? "").toBe("");
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

  it("a 50-fill burst is capped: one utterance of 3 in full plus the count", () => {
    const burst = Array.from({ length: 50 }, (_, i) =>
      fill({ qty: String(i + 1), accountId: i % 2 === 0 ? "acc-main" : "acc-hedge" }),
    );
    const say = vi.fn();
    announceFills(burst, MINE, undefined, say);
    expect(FILL_BATCH_CEILING).toBe(3);
    expect(say).toHaveBeenCalledWith(
      "assertive",
      "Filled: bought 1 BTCUSDT at 64,009, Main. Filled: bought 2 BTCUSDT at 64,009, Hedge. " +
        "Filled: bought 3 BTCUSDT at 64,009, Main. 47 more fills",
    );
  });

  it("batching: a batch is one write, single calls leave one message, an empty batch says nothing", () => {
    render(<ShellAnnouncer />);
    const burst = Array.from({ length: 50 }, (_, i) => fill({ qty: String(i + 1) }));
    act(() => burst.forEach((f) => announceFill(f, MINE)));
    const assertive = document.querySelector("[aria-live='assertive']") as HTMLElement;
    expect(assertive.children).toHaveLength(1);
    const say = vi.fn();
    const alert = vi.fn();
    announceFills(burst, MINE, undefined, say);
    announceFills(burst.slice(0, 2), MINE, { alert });
    announceFills([], MINE, undefined, say);
    expect(say).toHaveBeenCalledTimes(1);
    expect(alert).toHaveBeenCalledTimes(1);
  });
});

describe("the host grid's tree (C-14.1)", () => {
  it("grid / row / gridcell and aria-* have no serious or critical axe violation, before and after moving", async () => {
    // axe probes icon ligatures on a canvas jsdom lacks; without one it skips the probe.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const { container } = render(
      <Host levels={levels(60)} options={{ initial: { row: 20 }, windowRows: 12 }} />,
    );
    const grid = screen.getByRole("grid", { name: "Footprint" });
    expect(grid).toHaveAttribute("aria-rowcount", "60");
    expect(grid).toHaveAttribute("aria-colcount", "3");
    await expectNoSeriousAxe(container);
    act(() => stop().focus());
    for (const key of ["PageDown", "ArrowRight", "End", "ArrowDown"]) press(key);
    press("End", { ctrlKey: true });
    expect(focused().closest("[role='row']")).toHaveAttribute("aria-rowindex", "60");
    expect(focused()).toHaveAttribute("aria-colindex", "3");
    await expectNoSeriousAxe(container);
  });
});
