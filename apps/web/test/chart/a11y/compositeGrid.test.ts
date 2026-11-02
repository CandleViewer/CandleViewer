import { describe, expect, it } from "vitest";
import {
  clampIndex,
  createGridState,
  drawnRange,
  gridMoveOf,
  nearestDecimalKey,
  needsRecentre,
  reduceGrid,
  scrollToShow,
  tabIndexAt,
  windowOf,
  type GridConfig,
  type GridMove,
  type GridState,
} from "../../../src/chart/a11y/compositeGrid";

const LADDER: GridConfig = {
  rows: 200,
  cols: 1,
  page: "row",
  pageRows: 10,
  homeEnd: "col",
  windowRows: 40,
};
const FOOTPRINT: GridConfig = {
  rows: 30,
  cols: 12,
  page: "col",
  pageRows: 10,
  homeEnd: "col",
  windowRows: 30,
};
const move = (s: GridState, m: GridMove, keys?: readonly string[]): GridState =>
  reduceGrid(s, { type: "move", move: m }, keys);
const keyEvent = (
  key: string,
  mods: Partial<Record<"ctrl" | "shift" | "alt" | "meta", boolean>> = {},
) => ({
  key,
  ctrlKey: mods.ctrl ?? false,
  shiftKey: mods.shift ?? false,
  altKey: mods.alt ?? false,
  metaKey: mods.meta ?? false,
});

/** mulberry32: a seeded PRNG, so the property sweeps are deterministic. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const MOVES: readonly GridMove[] = [
  "up",
  "down",
  "left",
  "right",
  "pageUp",
  "pageDown",
  "home",
  "end",
  "first",
  "last",
];

describe("gridMoveOf: the keys the grid owns", () => {
  it("maps arrows, paging and the ends; Ctrl+Home/End reach the corners", () => {
    expect(gridMoveOf(keyEvent("ArrowUp"))).toBe("up");
    expect(gridMoveOf(keyEvent("ArrowDown"))).toBe("down");
    expect(gridMoveOf(keyEvent("ArrowLeft"))).toBe("left");
    expect(gridMoveOf(keyEvent("ArrowRight"))).toBe("right");
    expect(gridMoveOf(keyEvent("PageUp"))).toBe("pageUp");
    expect(gridMoveOf(keyEvent("PageDown"))).toBe("pageDown");
    expect(gridMoveOf(keyEvent("Home"))).toBe("home");
    expect(gridMoveOf(keyEvent("End"))).toBe("end");
    expect(gridMoveOf(keyEvent("Home", { ctrl: true }))).toBe("first");
    expect(gridMoveOf(keyEvent("End", { ctrl: true }))).toBe("last");
  });

  it("leaves Enter, Tab, chords and Ctrl+arrows to the host (no order key is the grid's)", () => {
    for (const k of ["Enter", "Tab", " ", "Delete", "a"])
      expect(gridMoveOf(keyEvent(k))).toBeNull();
    expect(gridMoveOf(keyEvent("Enter", { ctrl: true }))).toBeNull();
    expect(gridMoveOf(keyEvent("Delete", { ctrl: true }))).toBeNull();
    expect(gridMoveOf(keyEvent("ArrowUp", { ctrl: true }))).toBeNull();
    expect(gridMoveOf(keyEvent("ArrowUp", { shift: true }))).toBeNull();
    expect(gridMoveOf(keyEvent("ArrowUp", { alt: true }))).toBeNull();
    expect(gridMoveOf(keyEvent("ArrowUp", { meta: true }))).toBeNull();
  });
});

describe("reduceGrid at the edges", () => {
  it("the ladder: ↑ at the top and ↓ at the bottom stay put; PageUp/PageDown step a page and clamp", () => {
    let s = createGridState(LADDER);
    s = move(s, "up");
    expect(s.focus).toEqual({ row: 0, col: 0 });
    s = move(s, "pageDown");
    expect(s.focus.row).toBe(10);
    s = move(s, "last");
    expect(s.focus.row).toBe(199);
    s = move(s, "down");
    expect(s.focus.row).toBe(199);
    s = move(s, "pageDown");
    expect(s.focus.row).toBe(199);
    s = move(s, "pageUp");
    expect(s.focus.row).toBe(189);
    s = move(s, "home");
    expect(s.focus.row).toBe(0);
    s = move(s, "end");
    expect(s.focus.row).toBe(199);
  });

  it("the footprint: PageUp/PageDown move by bar, Home/End to the bar's first and last cell", () => {
    let s = createGridState(FOOTPRINT, { row: 5, col: 4 });
    s = move(s, "pageDown");
    expect(s.focus).toEqual({ row: 5, col: 5 });
    s = move(s, "pageUp");
    s = move(s, "pageUp");
    expect(s.focus).toEqual({ row: 5, col: 3 });
    s = move(s, "home");
    expect(s.focus).toEqual({ row: 0, col: 3 });
    s = move(s, "end");
    expect(s.focus).toEqual({ row: 29, col: 3 });
    s = move(s, "right");
    expect(s.focus).toEqual({ row: 29, col: 4 });
    s = move(s, "first");
    expect(s.focus).toEqual({ row: 0, col: 0 });
    s = move(s, "left");
    expect(s.focus).toEqual({ row: 0, col: 0 });
    s = move(s, "last");
    expect(s.focus).toEqual({ row: 29, col: 11 });
  });

  it("APG row ends: Home/End move along the row when homeEnd is row", () => {
    let s = createGridState({ ...FOOTPRINT, homeEnd: "row" }, { row: 3, col: 6 });
    s = move(s, "home");
    expect(s.focus).toEqual({ row: 3, col: 0 });
    s = move(s, "end");
    expect(s.focus).toEqual({ row: 3, col: 11 });
  });

  it("an empty grid keeps a stop at 0,0 and every move is a no-op", () => {
    let s = createGridState({ ...LADDER, rows: 0 });
    for (const m of MOVES) s = move(s, m);
    expect(s.focus).toEqual({ row: 0, col: 0 });
    expect(windowOf(s)).toEqual({ first: 0, last: 0 });
  });

  it("focus by pointer or AT moves the stop, clamped", () => {
    const s = reduceGrid(createGridState(FOOTPRINT), { type: "focus", row: 99, col: -3 });
    expect(s.focus).toEqual({ row: 29, col: 0 });
  });
});

describe("reduceGrid on data churn", () => {
  const prices = (from: number, n: number): string[] =>
    Array.from({ length: n }, (_, i) => String(from - i));

  it("the stop follows its row's key when the book shifts", () => {
    const keys = prices(64100, 200);
    let s = createGridState(LADDER, { row: 90 }, keys);
    expect(s.key).toBe("64010");
    const shifted = prices(64105, 200); // five new rows above: 64010 is now row 95
    s = reduceGrid(s, { type: "data", rows: 200, cols: 1 }, shifted);
    expect(s.focus.row).toBe(95);
    expect(s.key).toBe("64010");
  });

  it("a key that is gone clamps to the nearest row, and a shrunk grid clamps the stop", () => {
    const keys = prices(64100, 200);
    let s = createGridState(LADDER, { row: 150 }, keys);
    const fewer = prices(63000, 100); // 63950 is not among them
    s = reduceGrid(s, { type: "data", rows: 100, cols: 1 }, fewer);
    expect(s.focus.row).toBe(99);
    expect(s.key).toBe(fewer[99]);
    s = reduceGrid(s, { type: "data", rows: 10, cols: 1 });
    expect(s.focus.row).toBe(9);
    expect(s.key).toBeNull();
  });

  it("with nearestDecimalKey a gone key lands on the nearest price, not the same index (code m5)", () => {
    const keys = prices(64100, 200);
    let s = createGridState(LADDER, { row: 10 }, keys); // 64090
    const shifted = prices(64105, 205).filter((k) => k !== "64090");
    s = reduceGrid(s, { type: "data", rows: 204, cols: 1 }, shifted, nearestDecimalKey);
    expect(s.key).toBe("64091");
    const far = prices(63000, 50);
    s = reduceGrid(s, { type: "data", rows: 50, cols: 1 }, far, nearestDecimalKey);
    expect(s.key).toBe("63000");
  });

  it("nearestDecimalKey is exact on decimals and declines non-decimal keys", () => {
    expect(nearestDecimalKey("1.05", ["1", "1.1", "2"])).toBe(0); // a tie: the first
    expect(nearestDecimalKey("1.06", ["1", "1.1", "2"])).toBe(1);
    expect(nearestDecimalKey("-0.5", ["-2", "0.25", "3"])).toBe(1);
    expect(nearestDecimalKey("99999999999999999.01", ["99999999999999999", "1"])).toBe(0);
    expect(nearestDecimalKey("1", ["a", "2"])).toBe(-1);
    expect(nearestDecimalKey("1", [])).toBe(-1);
  });

  it("a window or page under one row is clamped to one (n2)", () => {
    const s = createGridState({ ...LADDER, windowRows: 0, pageRows: -3 }, { row: 5 });
    expect(s.windowRows).toBe(1);
    expect(s.pageRows).toBe(1);
    expect(windowOf(s)).toEqual({ first: 5, last: 5 });
    expect(reduceGrid(s, { type: "move", move: "pageDown" }).focus.row).toBe(6);
  });

  it("a move keeps the key it had when no keys are passed and the row did not change", () => {
    const keys = prices(64100, 200);
    const s = createGridState(LADDER, { row: 0 }, keys);
    expect(move(s, "up").key).toBe("64100");
    expect(move(s, "down").key).toBeNull();
  });
});

describe("reduceGrid properties (seeded sweeps)", () => {
  it("the stop is always inside the grid and inside the drawn window, and exactly one cell is tabbable", () => {
    const next = rng(1358);
    for (let run = 0; run < 200; run++) {
      const rows = Math.floor(next() * 300);
      const cols = 1 + Math.floor(next() * 8);
      const windowRows = 1 + Math.floor(next() * 50);
      let s = createGridState({ ...FOOTPRINT, rows, cols, windowRows });
      for (let i = 0; i < 40; i++) {
        const r = next();
        if (r < 0.1) {
          s = reduceGrid(s, {
            type: "data",
            rows: Math.floor(next() * 300),
            cols: 1 + Math.floor(next() * 8),
          });
        } else {
          s = move(s, MOVES[Math.floor(next() * MOVES.length)] ?? "up");
        }
        const w = windowOf(s);
        expect(s.focus.row).toBeGreaterThanOrEqual(0);
        expect(s.focus.row).toBeLessThanOrEqual(Math.max(s.rows - 1, 0));
        expect(s.focus.col).toBeLessThanOrEqual(Math.max(s.cols - 1, 0));
        expect(s.focus.row).toBeGreaterThanOrEqual(w.first);
        expect(s.focus.row).toBeLessThanOrEqual(w.last);
        expect(w.last - w.first + 1).toBeLessThanOrEqual(s.windowRows);
        expect(tabIndexAt(s, s.focus.row, s.focus.col)).toBe(0);
        expect(tabIndexAt(s, s.focus.row + 1, s.focus.col)).toBe(-1);
      }
    }
  });

  it("Home, End, Ctrl+Home and Ctrl+End are idempotent", () => {
    const next = rng(47);
    for (let run = 0; run < 100; run++) {
      let s = createGridState(
        { ...FOOTPRINT, rows: 1 + Math.floor(next() * 100), cols: 1 + Math.floor(next() * 10) },
        { row: Math.floor(next() * 100), col: Math.floor(next() * 10) },
      );
      for (const m of ["home", "end", "first", "last"] as const) {
        const once = move(s, m);
        expect(move(once, m).focus).toEqual(once.focus);
        s = once;
      }
    }
  });

  it("↓ then ↑ returns to the start away from the edges", () => {
    const s = createGridState(LADDER, { row: 50 });
    expect(move(move(s, "down"), "up").focus).toEqual(s.focus);
    expect(move(move(s, "pageDown"), "pageUp").focus).toEqual(s.focus);
  });
});

describe("window helpers (shared with SCR-045)", () => {
  it("clampIndex, drawnRange and needsRecentre", () => {
    expect(clampIndex(-1, 0, 5)).toBe(0);
    expect(clampIndex(9, 0, 5)).toBe(5);
    expect(drawnRange({ first: 10, last: 20 }, 100, 30)).toEqual({ first: 0, last: 50 });
    expect(drawnRange({ first: 0, last: 0 }, 0, 30)).toEqual({ first: 0, last: 0 });
    expect(needsRecentre(40, { first: 0, last: 100 }, 30)).toBe(false);
    expect(needsRecentre(10, { first: 0, last: 100 }, 30)).toBe(true);
    expect(needsRecentre(90, { first: 0, last: 100 }, 30)).toBe(true);
  });

  it("scrollToShow scrolls the least and stays inside the list", () => {
    expect(scrollToShow(0, 40, 10, 200)).toBe(0);
    expect(scrollToShow(0, 40, 45, 200)).toBe(6);
    expect(scrollToShow(50, 40, 20, 200)).toBe(20);
    expect(scrollToShow(190, 40, 199, 200)).toBe(160);
    expect(scrollToShow(0, 40, 5, 10)).toBe(0);
  });
});
