// `axis-ticks` scene (E11-S06, README BQ-204): one chart's axes over 5 000 1 m bars, each step a
// 3 px pan with autoscale's window moving too, so every step rebuilds both axes: candidates,
// decimation, the grid ring and the label lists. The ticket's budget is ≤ 0.5 ms per axis per
// frame; the .perf.test.ts times both axes together against 1 ms, the counted test the output.
// The label draw itself is E11-S11's (G-47): this scene times the model, not glyphs. A zone other
// than UTC reads its offsets from the clock's per-hour cache (BQ-203), timed as its own case.
import { AxisModel, type AxisLayout } from "../../src/axes/axis-model.js";
import { BarStore } from "../../src/model/BarStore.js";
import { ChartViewport, type PaneTransform } from "../../src/viewport/index.js";
import { bars } from "./pan-zero-upload.js";

const W = 1920;
const H = 1080;
const GUTTER = 64;
const THEME = {
  "color.grid.line": "#1e2329",
  "color.border.default": "#2b3139",
  "color.text.tertiary": "#848e9c",
};

export class AxisTicksBench {
  readonly viewport: ChartViewport;
  readonly axes: AxisModel;
  readonly layout: { -readonly [K in keyof AxisLayout]: AxisLayout[K] } = {
    width: W,
    height: H,
    priceGutter: GUTTER,
    panes: [{ rect: [0, 0, W - GUTTER, H - 24] }],
    timeAxis: [0, H - 24, W - GUTTER, 24],
  };
  rebuilt = 0;
  private turn = 0;

  constructor(n = 5_000, timeZone = "UTC") {
    this.axes = new AxisModel(timeZone);
    const store = new BarStore();
    store.append(bars(n));
    this.viewport = new ChartViewport(store);
    this.viewport.setSize(W - GUTTER, H - 24, 2);
    this.viewport.setPanePlot(0, 0, H - 24);
    this.viewport.setPriceInfo(0, 0, 0.5);
    this.viewport.scrollTo(n - 400, 4);
    this.step(); // the first frame measures the gutter, as the runtime lays out again with it
    this.layout.priceGutter = this.axes.gutter.width;
    this.rebuilt = 0;
  }

  /** One frame: a 3 px pan and a moved price window, then the axes. */
  step(): void {
    const vp = this.viewport;
    this.turn += 1;
    vp.pan(3);
    const low = 120_000 + (this.turn % 50);
    vp.setPriceRange(0, low, low + 800 + (this.turn % 7));
    (vp.panes[0] as PaneTransform).autoScale = true;
    if (this.axes.update(vp, this.layout, THEME) !== 0) this.rebuilt += 1;
  }
}
