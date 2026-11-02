// E22-S01 (#714) PR-B: the windowed grid writer (C-70): at most 60 row nodes, one write pass per
// frame that touches only changed slots, no transform / transition / animation on any row or the
// list, the tier set with the row's first frame and never changed, identical under reduced motion.
import { beforeEach, describe, expect, it } from "vitest";
import { DisplayList } from "../../../src/features/tape/model/displayList";
import {
  FLAG_BIG,
  FLAG_LIQUIDATION,
  SIDE_BUY,
  SIDE_SELL,
  TapeRing,
  type TapeSide,
} from "../../../src/features/tape/model/ring";
import {
  GridWriter,
  MAX_DOM_ROWS,
  POOL_SIZE,
  ROW_HEIGHT_PX,
  type TierOf,
} from "../../../src/features/tape/view/gridWriter";

let grid: HTMLDivElement;
let body: HTMLDivElement;
let win: HTMLDivElement;

beforeEach(() => {
  document.body.innerHTML = "";
  grid = document.createElement("div");
  body = document.createElement("div");
  win = document.createElement("div");
  body.append(win);
  grid.append(body);
  document.body.append(grid);
});

const push = (ring: TapeRing, n: number, flags = 0, side: TapeSide = SIDE_BUY): number =>
  ring.push({
    id: `t${n}`,
    tsMs: new Date(2026, 9, 31, 14, 2, 11, n % 1000).getTime(),
    price: "64012.0",
    size: "18.75",
    side,
    flags,
    clusterSize: 1,
  }) ?? -1;

const setup = (capacity = 1_000, tierOf?: TierOf) => {
  const ring = new TapeRing(capacity);
  const list = new DisplayList(ring);
  const writer = new GridWriter(grid, body, win, ring, "BTCUSDT", "tg", tierOf);
  const draw = (first = 0, activeKey: number | null = null) => {
    list.build(ring.nextSeq - 1);
    return writer.render(list, {
      first,
      activeKey,
      activeCol: 0,
      selected: activeKey !== null,
      focused: true,
    });
  };
  return { ring, list, writer, draw };
};

const shownRows = () =>
  [...win.querySelectorAll<HTMLElement>('[role="row"]')].filter((r) => r.style.display !== "none");

describe("tape grid writer", () => {
  it("creates a fixed pool once: with the header, never more than 60 row nodes (SCR-053)", () => {
    const { ring, draw } = setup();
    for (let k = 0; k < 500; k += 1) push(ring, k);
    draw();
    expect(win.querySelectorAll('[role="row"]').length).toBe(POOL_SIZE);
    expect(POOL_SIZE + 1).toBe(MAX_DOM_ROWS);
    expect(body.style.height).toBe(`${500 * ROW_HEIGHT_PX}px`);
    expect(grid.getAttribute("aria-rowcount")).toBe("501");
  });

  it("S01-u-01: writes only the slots whose print changed, newest first, in one pass", () => {
    const { ring, draw } = setup();
    for (let k = 0; k < 3; k += 1) push(ring, k);
    expect(draw().written).toBe(3);
    expect(draw().written).toBe(0); // nothing changed: nothing written
    push(ring, 3);
    const stats = draw();
    expect(stats.written).toBe(4); // in place: every shown slot now holds the next-older print
    const names = shownRows().map((r) => r.getAttribute("aria-rowindex"));
    expect(names).toEqual(["2", "3", "4", "5"]);
  });

  it("BQ-215: rewrites a row's text in place, keeping its Text nodes (no node churn per print)", () => {
    const { ring, draw } = setup();
    for (let k = 0; k < 3; k += 1) push(ring, k);
    draw();
    const time = (shownRows()[0] as HTMLElement).querySelector('[role="gridcell"]') as HTMLElement;
    const nodes = [...time.querySelectorAll("span")].map((s) => s.firstChild);
    const before = time.textContent;
    push(ring, 3);
    draw();
    expect(time.textContent).not.toBe(before); // the newest print moved into the top slot
    expect([...time.querySelectorAll("span")].map((s) => s.firstChild)).toEqual(nodes);
    for (const node of nodes) expect(node?.nodeType).toBe(Node.TEXT_NODE);
  });

  it("BQ-215: a limit caps the shown slots and hides the rest of the pool", () => {
    const { ring, list, writer } = setup();
    for (let k = 0; k < 70; k += 1) push(ring, k);
    list.build(ring.nextSeq - 1);
    const input = { first: 0, activeKey: null, activeCol: 0, selected: false, focused: false };
    expect(writer.render(list, input).shown).toBe(POOL_SIZE);
    const stats = writer.render(list, { ...input, limit: 29 });
    expect(stats.shown).toBe(29);
    expect(stats.written).toBe(POOL_SIZE - 29); // only the slots it hid
    expect(shownRows()).toHaveLength(29);
    expect(GridWriter.windowSize(70, 0, 29)).toBe(29);
    expect(GridWriter.windowSize(70, 0, 500)).toBe(POOL_SIZE);
  });

  it("S01-u-04 / S01-u-05: no transform, translate, transition or animation on any row or the list", () => {
    const { ring, draw } = setup();
    for (let k = 0; k < 80; k += 1)
      push(ring, k, k % 5 === 0 ? FLAG_BIG : 0, k % 2 ? SIDE_SELL : SIDE_BUY);
    draw();
    draw(10);
    const every = [win, body, ...win.querySelectorAll<HTMLElement>("*")];
    for (const el of every) {
      for (const prop of ["transform", "translate", "transition", "animation"]) {
        expect(el.style.getPropertyValue(prop)).toBe("");
      }
    }
    expect(win.style.top).toBe(`${10 * ROW_HEIGHT_PX}px`); // the window moves by `top`, never a transform
  });

  it("S01-u-02: a tier-1 row carries weight, glyph and accent with its first write and keeps them", () => {
    const { ring, draw } = setup();
    push(ring, 0, FLAG_BIG, SIDE_SELL);
    draw();
    const row = shownRows()[0] as HTMLElement;
    const before = row.outerHTML;
    expect(row.dataset["tier"]).toBe("1");
    expect(row.style.borderLeftColor).toBe("var(--color-sell-default)");
    expect(row.textContent).toContain("●");
    expect(row.getAttribute("aria-label")).toBe(
      "Sell, 18.75 BTC at 64,012.0, 1.2M, big, 14:02:11.000",
    );
    draw();
    expect(row.outerHTML).toBe(before); // never changed on screen
  });

  it("S01-u-02: tier 2 (an injected rule, S02's) takes the subtle fill and the undimmed prefix", () => {
    const tierOf: TierOf = (flags) => ((flags & FLAG_BIG) !== 0 ? 2 : 0);
    const { ring, draw } = setup(1_000, tierOf);
    push(ring, 0, FLAG_BIG, SIDE_BUY);
    push(ring, 1, 0, SIDE_BUY);
    draw();
    const [newest, whale] = shownRows() as [HTMLElement, HTMLElement];
    expect(whale.style.background).toBe("var(--color-buy-subtle)");
    expect(whale.textContent).toContain("◆");
    expect(whale.getAttribute("aria-label")).toContain(", whale, ");
    expect((whale.querySelector("span") as HTMLElement).style.color).toBe(
      "var(--color-text-primary)",
    );
    expect((newest.querySelector("span") as HTMLElement).style.color).toBe(
      "var(--color-text-tertiary)",
    );
    expect(newest.style.borderLeftColor).toBe("transparent");
  });

  it("writes the time with milliseconds, the side glyph before the price and the tags after the word", () => {
    const { ring, draw } = setup();
    ring.push({
      id: "x",
      tsMs: new Date(2026, 9, 31, 9, 5, 3, 7).getTime(),
      price: "64012.5",
      size: "4.00",
      side: SIDE_BUY,
      flags: FLAG_LIQUIDATION,
      clusterSize: 7,
    });
    draw();
    const cells = [...(shownRows()[0] as HTMLElement).querySelectorAll('[role="gridcell"]')].map(
      (c) => c.textContent,
    );
    expect(cells).toEqual(["09:05:03.007", "▲64,012.5", "4.00", "256.1k", "Buy×7 liq"]);
  });

  it("marks the active cell for aria-activedescendant and the row selected", () => {
    const { ring, draw } = setup();
    for (let k = 0; k < 5; k += 1) push(ring, k);
    draw(0, 3);
    const id = grid.getAttribute("aria-activedescendant");
    expect(id).toBe("tg-r1-c0");
    expect(document.getElementById(id ?? "")?.style.outline).toBe(
      "2px solid var(--color-focus-ring)",
    );
    expect(document.getElementById("tg-r1")?.getAttribute("aria-selected")).toBe("true");
    draw(0, null);
    expect(grid.hasAttribute("aria-activedescendant")).toBe(false);
  });

  it("renders a divider as a presentation row, never a focus target, and back again", () => {
    const { ring, list, writer } = setup();
    for (let k = 0; k < 3; k += 1) push(ring, k);
    list.addDivider(1, "— 2 prints while paused —");
    list.build(2);
    writer.render(list, {
      first: 0,
      activeKey: null,
      activeCol: 0,
      selected: false,
      focused: false,
    });
    const divider = win.querySelector('[role="presentation"]') as HTMLElement;
    expect(divider.textContent).toBe("— 2 prints while paused —");
    expect(divider.hasAttribute("aria-rowindex")).toBe(false);
    const fresh = new DisplayList(ring);
    fresh.build(2);
    writer.render(fresh, {
      first: 0,
      activeKey: null,
      activeCol: 0,
      selected: false,
      focused: false,
    });
    expect(win.querySelector('[role="presentation"]')).toBeNull();
  });

  it("places the window by the scroll position with overscan and hides the unused slots", () => {
    expect(GridWriter.firstFor(0, 1_000)).toBe(0);
    expect(GridWriter.firstFor(100 * ROW_HEIGHT_PX, 1_000)).toBe(90);
    expect(GridWriter.firstFor(990 * ROW_HEIGHT_PX, 1_000)).toBe(1_000 - POOL_SIZE);
    expect(GridWriter.windowSize(5, 0)).toBe(5);
    const { ring, draw } = setup();
    for (let k = 0; k < 70; k += 1) push(ring, k);
    draw();
    expect(shownRows()).toHaveLength(POOL_SIZE);
    const ring2 = new TapeRing(10);
    const list2 = new DisplayList(ring2);
    list2.build(-1);
    const w2 = new GridWriter(grid, body, document.createElement("div"), ring2, "BTCUSDT", "t2");
    expect(
      w2.render(list2, { first: 0, activeKey: null, activeCol: 0, selected: false, focused: false })
        .shown,
    ).toBe(0);
  });
});
