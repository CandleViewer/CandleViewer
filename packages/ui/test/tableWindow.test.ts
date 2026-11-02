import { describe, expect, it } from "vitest";
import { bodyParts, rowsInView } from "../src/components/internal/tableWindow.js";

// The rows a scrolled region shows below its sticky header, as absolute indices (CMP-049's window seam).
const view = {
  scrollTop: 0,
  viewHeight: 120,
  bodyTop: 24,
  headerHeight: 24,
  rowHeight: 24,
  total: 120,
};

describe("rowsInView", () => {
  it("at the top: the rows under the header that fit the view", () => {
    expect(rowsInView(view)).toEqual({ first: 0, last: 3 });
  });

  it("scrolled: the rows the sticky header leaves visible", () => {
    expect(rowsInView({ ...view, scrollTop: 240 })).toEqual({ first: 10, last: 13 });
  });

  it("a partly visible row counts at either edge", () => {
    expect(rowsInView({ ...view, scrollTop: 250 })).toEqual({ first: 10, last: 14 });
  });

  it("clamps to the list's last row", () => {
    expect(rowsInView({ ...view, scrollTop: 99_999 })).toEqual({ first: 119, last: 119 });
  });

  it("nothing laid out (no row height or no rows): no view", () => {
    expect(rowsInView({ ...view, rowHeight: 0 })).toBeUndefined();
    expect(rowsInView({ ...view, total: 0 })).toBeUndefined();
  });
});

// A windowed body's children (G-01: the window and, at most, the one remembered row outside it).
describe("bodyParts", () => {
  /** Each drawn row's child position, from 1, so `:nth-child(even)` reads as the list's. */
  const places = (drawn: readonly number[], total: number): number[] =>
    bodyParts(drawn, total).flatMap((part, i) => (part.kind === "row" ? [i + 1] : []));
  const rowsHeld = (drawn: readonly number[], total: number): number =>
    bodyParts(drawn, total).reduce(
      (sum, part) => sum + (part.kind === "row" ? 1 : part.kind === "spacer" ? part.rows : 0),
      0,
    );

  it("a window alone: one spacer before it (the pad first on an even offset), then one after", () => {
    expect(bodyParts([4, 5, 6], 10)).toEqual([
      { kind: "spacer", key: "cv-before", rows: 3 },
      { kind: "row", r: 4 },
      { kind: "row", r: 5 },
      { kind: "row", r: 6 },
      { kind: "spacer", key: "cv-after", rows: 4 },
    ]);
    for (let offset = 0; offset < 12; offset += 1) {
      const drawn = [offset + 1, offset + 2];
      const lead = bodyParts(drawn, 20).findIndex((part) => part.kind === "row");
      // No spacer at the top; one on an odd offset; on an even one, the pad and the spacer.
      expect(lead).toBe(offset === 0 ? 0 : offset % 2 === 1 ? 1 : 2);
    }
  });

  it("the kept row before or after the window: every drawn row on its own parity, every row held once", () => {
    for (const [drawn, total] of [
      [[3, 61, 62, 63], 100],
      [[2, 40, 41], 50],
      [[1, 2, 3, 30], 40],
      [[10, 11, 12, 13, 50], 50],
      [[9, 10, 11, 25], 25],
    ] as const) {
      expect(places(drawn, total).map((p) => p % 2)).toEqual(drawn.map((r) => r % 2));
      expect(rowsHeld(drawn, total)).toBe(total);
      const keys = bodyParts(drawn, total).flatMap((p) => (p.kind === "row" ? [] : [p.key]));
      expect(new Set(keys).size).toBe(keys.length);
    }
  });

  it("names the gap between the kept row and the window apart from the leading one", () => {
    expect(bodyParts([3, 61], 61).map((p) => (p.kind === "row" ? p.r : p.key))).toEqual([
      "cv-pad",
      "cv-before",
      3,
      "cv-gap",
      61,
    ]);
  });
});
