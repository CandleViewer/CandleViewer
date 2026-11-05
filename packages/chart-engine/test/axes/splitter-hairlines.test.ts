// E11-S09 PR 1b (E11-D02 §8, BQ-23): the splitter hairlines are instances of the one grid ring,
// full width with the gutter, and a moved boundary rebuilds them even when pane 0 did not move.
import { describe, expect, it } from "vitest";
import { AxisModel } from "../../src/axes/axis-model.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { minuteMap } from "../interaction/fixtures.js";

type Rect = [number, number, number, number];
const STRIDE = 9;
const THEME = {}; // the signature compares the theme by identity

function setup() {
  const vp = new ChartViewport(minuteMap());
  vp.setSize(1200, 600, 1);
  vp.setPanePlot(0, 0, 200);
  vp.setPriceInfo(0, 0, 0.5);
  vp.setPriceRange(0, 127_800, 128_600);
  const rows = (...ys: number[]): { rect: Rect }[] =>
    ys.slice(0, -1).map((y, i) => ({ rect: [0, y, 1200, (ys[i + 1] ?? 0) - y] }));
  const layout = (...ys: number[]) => ({
    width: 1261,
    height: 624,
    priceGutter: 61,
    panes: rows(...ys),
    timeAxis: [0, 600, 1200, 24] as Rect,
  });
  /** The grid's full-width horizontals (x 0 to 1261 device px), as CSS y. */
  const hairlines = (m: AxisModel): number[] => {
    const out: number[] = [];
    for (let i = 0; i < m.grid.count; i += 1) {
      const [x0, y0, x1, y1] = m.grid.data.subarray(i * STRIDE, i * STRIDE + 4);
      if (x0 === 0 && x1 === 1261 && y0 === y1) out.push(624 - (y0 ?? 0));
    }
    return out.map(Math.floor);
  };
  return { vp, layout, hairlines };
}

describe("E11-S09 PR 1b: splitter hairlines in the grid ring", () => {
  it("draws one full-width hairline per boundary and none for a single pane", () => {
    const { vp, layout, hairlines } = setup();
    const one = new AxisModel();
    one.update(vp, layout(0, 600), {});
    expect(hairlines(one)).toEqual([]);
    const three = new AxisModel();
    three.update(vp, layout(0, 200, 400, 600), {});
    expect(hairlines(three)).toEqual([200, 400]);
  });

  it("a boundary that moves below pane 0 still rewrites the ring", () => {
    const { vp, layout, hairlines } = setup();
    const m = new AxisModel();
    m.update(vp, layout(0, 200, 400, 600), THEME);
    expect(m.update(vp, layout(0, 200, 400, 600), THEME)).toBe(0); // still: a compare
    expect(m.update(vp, layout(0, 200, 450, 600), THEME)).not.toBe(0);
    expect(hairlines(m)).toEqual([200, 450]);
  });
});
