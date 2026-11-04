// `axis-ticks` scene (E11-S06, README BQ-204): one chart's axes over 5 000 1 m bars, each step a
// 3 px pan with autoscale's window moving too, so every step rebuilds both axes: candidates,
// decimation, the grid ring and the label lists. The ticket's budget is ≤ 0.5 ms per axis per
// frame; the .perf.test.ts times both axes together against 1 ms, the counted test the output.
// The label draw itself is E11-S11's (G-47): this scene times the model, not glyphs. A zone other
// than UTC reads its offsets from the clock's constant-offset runs (BQ-203), timed as its own
// case; the DAILY and WEEKLY shapes (a 2000 px plot of 1-day bars at 12 px, zoomed-out 1-week
// bars at 2 px) take the day and month loops, which visit every day or month in view.
import { AxisModel, type AxisLayout } from "../../src/axes/axis-model.js";
import { BarStore } from "../../src/model/BarStore.js";
import { ChartViewport, type PaneTransform } from "../../src/viewport/index.js";
import { bars } from "./pan-zero-upload.js";

const H = 1080;
const DAY_US = 86_400e6;

/** A scene shape: bar length, bar spacing, the pan per frame and the chart width. */
export interface AxisShape {
  readonly barUs: number;
  readonly spacing: number;
  readonly panPx: number;
  readonly width: number;
}
/** E11-S06's scene: 1-minute bars at 4 px, 3 px pans on a 1920 px chart. */
export const MINUTE: AxisShape = { barUs: 60e6, spacing: 4, panPx: 3, width: 1920 };
/** A 2000 px plot of 1-day bars at 12 px (the week step: the day loop), 1.7 px pans. */
export const DAILY: AxisShape = { barUs: DAY_US, spacing: 12, panPx: 1.7, width: 2000 + 64 };
/** Zoomed-out 1-week bars at 2 px (the year step: the month loop over ~19 years). */
export const WEEKLY: AxisShape = { barUs: 7 * DAY_US, spacing: 2, panPx: 1.7, width: 2000 + 64 };
const GUTTER = 64;
const THEME = {
  "color.grid.line": "#1e2329",
  "color.border.default": "#2b3139",
  "color.text.tertiary": "#848e9c",
};

export class AxisTicksBench {
  readonly viewport: ChartViewport;
  readonly axes: AxisModel;
  readonly layout: { -readonly [K in keyof AxisLayout]: AxisLayout[K] };
  rebuilt = 0;
  private turn = 0;

  constructor(
    n = 5_000,
    timeZone = "UTC",
    readonly shape: AxisShape = MINUTE,
  ) {
    const W = shape.width;
    this.layout = {
      width: W,
      height: H,
      priceGutter: GUTTER,
      panes: [{ rect: [0, 0, W - GUTTER, H - 24] }],
      timeAxis: [0, H - 24, W - GUTTER, 24],
    };
    this.axes = new AxisModel(timeZone);
    const store = new BarStore();
    const batch = bars(n);
    const t0 = Date.UTC(2026, 0, 1) * 1000 - n * shape.barUs; // the last bar in 2026
    if (shape !== MINUTE) for (let i = 0; i < n; i += 1) batch.time[i] = t0 + i * shape.barUs;
    store.append(batch);
    this.viewport = new ChartViewport(store);
    this.viewport.setSize(W - GUTTER, H - 24, 2);
    this.viewport.setPanePlot(0, 0, H - 24);
    this.viewport.setPriceInfo(0, 0, 0.5);
    const visible = (W - GUTTER) / shape.spacing;
    this.viewport.scrollTo(shape === MINUTE ? n - 400 : n - visible - 200, shape.spacing);
    this.step(); // the first frame measures the gutter, as the runtime lays out again with it
    this.layout.priceGutter = this.axes.gutter.width;
    this.rebuilt = 0;
  }

  /** One frame: a pan (back the other way when `dir` is -1) and a moved price window, then the axes. */
  step(dir = 1): void {
    const vp = this.viewport;
    this.turn += 1;
    vp.pan(dir * this.shape.panPx);
    const low = 120_000 + (this.turn % 50);
    vp.setPriceRange(0, low, low + 800 + (this.turn % 7));
    (vp.panes[0] as PaneTransform).autoScale = true;
    if (this.axes.update(vp, this.layout, THEME) !== 0) this.rebuilt += 1;
  }
}
