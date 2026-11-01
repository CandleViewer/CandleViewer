/** E08-S08 (#4702): SCR-100's live window inside the 40-symbol cap (E08-D07 D6, §4.6). Pure: no layout, no clock. */
import { describe, expect, it } from "vitest";
import { coversView, liveWindow } from "../../../src/features/watchlist/liveWindow";

const range = (from: number, to: number): number[] =>
  Array.from({ length: to - from + 1 }, (_, i) => from + i);

describe("liveWindow", () => {
  it("a list within the budget is wholly live", () => {
    expect(liveWindow(12, 39, null, null)).toEqual(range(0, 11));
    expect(liveWindow(12, 39, { first: 4, last: 8 }, 6)).toEqual(range(0, 11));
  });

  it("before anything is laid out a longer list takes the rows from the top (rows 1–39 of Alts)", () => {
    expect(liveWindow(120, 39, null, null)).toEqual(range(0, 38));
  });

  it("a longer list takes a block around the rows in view, re-centred on the view and clamped to the list", () => {
    expect(liveWindow(120, 39, { first: 30, last: 44 }, null)).toEqual(range(18, 56));
    expect(liveWindow(120, 39, { first: 110, last: 119 }, null)).toEqual(range(81, 119));
    expect(liveWindow(120, 39, { first: 0, last: 14 }, null)).toEqual(range(0, 38));
  });

  it("always holds the focused row, at the expense of the block's row farthest from the view", () => {
    const window = liveWindow(120, 39, { first: 30, last: 44 }, 100);
    expect(window).toHaveLength(39);
    expect(window).toContain(100);
    expect(window).toEqual([...range(18, 55), 100]);
  });

  it("a budget smaller than the rows in view takes the focused row, then the rows in view from the top", () => {
    expect(liveWindow(120, 10, { first: 20, last: 34 }, 30)).toEqual([...range(20, 28), 30]);
    expect(liveWindow(120, 10, { first: 20, last: 34 }, null)).toEqual(range(20, 29));
  });

  it("no budget, no window", () => {
    expect(liveWindow(120, 0, { first: 0, last: 14 }, 3)).toEqual([]);
    expect(liveWindow(0, 39, null, null)).toEqual([]);
  });
});

describe("coversView", () => {
  it("a window moves only when a row in view (or the focused row) falls outside it", () => {
    const window = new Set(range(0, 38));
    expect(coversView(window, { first: 10, last: 24 }, null)).toBe(true);
    expect(coversView(window, { first: 30, last: 44 }, null)).toBe(false);
    expect(coversView(window, { first: 10, last: 24 }, 50)).toBe(false);
  });
});
