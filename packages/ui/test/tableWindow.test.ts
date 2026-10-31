import { describe, expect, it } from "vitest";
import { rowsInView } from "../src/components/internal/tableWindow.js";

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
