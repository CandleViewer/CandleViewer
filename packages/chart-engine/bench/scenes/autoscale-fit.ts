// `autoscale-fit` scene (E11-S05, BQ-126): one pane, 40 000 visible bars of a 100 000-bar series
// (2 000 px at the 0.05 px minimum spacing), each step panning one bar so the integer visible
// range changes and the AutoScaler refits once. 06 §4.3's ≤ 2 ms data-window stage holds it; the
// .perf.test.ts times it, the counted test checks one refit per step and no allocation growth.
// E12-S11 PR A1: the `series` variant reads the same bars through the runtime's source, a
// `BarStore` and its drawn `CandleRing` (`SeriesPriceSource`), and `feed` is a live tick: the
// source's version bumps, so the frame re-runs the log guard's full pass as well as the fit.
import { CandleRing } from "../../src/layers/candle/ring.js";
import { SeriesPriceSource } from "../../src/layers/candle/price-source.js";
import { BarStore } from "../../src/model/BarStore.js";
import {
  AutoScaler,
  ChartViewport,
  columnSource,
  type ExtentColumns,
  type IndexTimeMap,
  type PriceExtentSource,
} from "../../src/viewport/index.js";

/** A uniform 1-minute map of n bars (the BQ-111 map). */
const minuteMapOf = (n: number): IndexTimeMap => ({
  length: n,
  barDurationUs: 60e6,
  indexToTime: (i) => (i >= 0 && i < n ? i * 60e6 : Number.NaN),
  timeToIndex: (t) => (t < 0 ? -1 : Math.min(n - 1, Math.floor(t / 60e6))),
});

export const VISIBLE = 40_000;

export class AutoscaleFitBench {
  readonly viewport: ChartViewport;
  readonly scaler: AutoScaler;
  /** The `series` variant's source (null for `columns`). */
  readonly series: SeriesPriceSource | null = null;

  constructor(n = 100_000, variant: "columns" | "series" = "columns") {
    const low = new Int32Array(n);
    const high = new Int32Array(n);
    for (let i = 0; i < n; i += 1) {
      low[i] = 100_000 + ((i * 7919) % 5_000);
      high[i] = (low[i] as number) + 1 + (i % 40);
    }
    const cols: ExtentColumns = { low, high, close: high, length: n };
    let source: PriceExtentSource[];
    if (variant === "series") {
      const store = new BarStore({ maxBars: n });
      const ring = new CandleRing();
      const time = Float64Array.from({ length: n }, (_, i) => i * 60e6);
      const volume = new Float32Array(n);
      const b = { time, open: low, high, low, close: high, volume, priceOrigin: 0, tickSize: 0.5 };
      ring.sync(store, store.replace(b));
      this.viewport = new ChartViewport(store);
      this.series = new SeriesPriceSource(store, ring, this.viewport, 0);
      source = [this.series];
    } else {
      this.viewport = new ChartViewport(minuteMapOf(n));
      source = [columnSource(() => cols)];
    }
    this.viewport.setSize(2_000, 1_000, 1);
    this.viewport.setPanePlot(0, 0, 1_000);
    this.viewport.setPriceInfo(0, 0, 0.5);
    this.viewport.scrollTo(n / 2 - VISIBLE / 2, 0.05);
    this.scaler = new AutoScaler(this.viewport, () => source);
    this.scaler.update();
  }

  /** One frame after a one-bar pan: one refit over the visible slice. */
  step(): boolean {
    this.viewport.scrollTo(this.viewport.leftIndex + 1);
    return this.scaler.update();
  }

  /** E12-S11: one frame after a live tick on the series: the guard's pass plus one refit. */
  feed(): boolean {
    this.series?.bump();
    return this.scaler.update();
  }
}
