// E11-Q05 (#517) chart accessibility harness: an e2e-only page, built by ./vite.config.ts and never
// by the app's build (test/e2e-a11y-chart-harness.test.ts). It mounts the engine's `createChart`
// from `main` with a seeded synthetic candle series (no network, C-13.5) so the a11y collectors
// can audit the chart surface. `?state=` picks a state of surfaces.ts.
import { createChart, type CandleData, type ChartOptions } from "@candleviewer/chart-engine";

/**
 * The DOM mirror option of E11-S13 (#5480, `ChartOptions.a11y.mirror`) is not on `main`. The
 * harness asks for it anyway and detects at runtime whether the engine honoured it, so the audit
 * records "not assessed: surrogate not on main" instead of passing on an absent mirror.
 */
type HarnessOptions = ChartOptions & { readonly a11y?: { readonly mirror: boolean } };

/** What the collectors read back from `window.__cvChartHarness`. */
export interface HarnessReport {
  readonly state: string;
  readonly mirrorRequested: boolean;
  /** The engine built the E11-S13 mirror root (`[data-cv-chart-root]`). */
  readonly mirrorEngaged: boolean;
  readonly bars: number;
}

const BARS = 500;
const TICK_SIZE = 0.1;

/** Seeded random-walk candles (LCG, fixed seed): the same bars on every run. */
function seededCandles(n: number): CandleData {
  let seed = 517;
  const rnd = (): number => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32;
  const d: CandleData = {
    time: new Float64Array(n),
    open: new Int32Array(n),
    high: new Int32Array(n),
    low: new Int32Array(n),
    close: new Int32Array(n),
    volume: new Float32Array(n),
    priceOrigin: 0,
    tickSize: TICK_SIZE,
  };
  const t0 = Date.UTC(2026, 0, 1) * 1000; // µs epoch
  let last = 600_000; // 60 000.0 in ticks
  for (let i = 0; i < n; i++) {
    const open = last;
    const close = open + Math.round((rnd() - 0.5) * 400);
    d.time[i] = t0 + i * 60_000_000;
    d.open[i] = open;
    d.close[i] = close;
    d.high[i] = Math.max(open, close) + Math.round(rnd() * 150);
    d.low[i] = Math.min(open, close) - Math.round(rnd() * 150);
    d.volume[i] = 1 + rnd() * 50;
    last = close;
  }
  return d;
}

const state = new URLSearchParams(window.location.search).get("state") ?? "mirror";
const container = document.getElementById("chart");
if (container === null) throw new Error("harness: #chart is missing from index.html");

const options: HarnessOptions = {
  container,
  theme: {
    palette: "default",
    convention: "standard",
    colors: {
      "color.chart.background": "#0b0e11",
      "color.candle.up": "#26a69a",
      "color.candle.down": "#ef5350",
    },
  },
  a11y: { mirror: state !== "mirror-off" },
};
const chart = createChart(options);
chart
  .addPane({})
  .addSeries("candles", { upColorToken: "color.candle.up", downColorToken: "color.candle.down" })
  .setData(seededCandles(BARS));

const report: HarnessReport = {
  state,
  mirrorRequested: options.a11y?.mirror === true,
  mirrorEngaged: container.querySelector("[data-cv-chart-root]") !== null,
  bars: BARS,
};
(window as unknown as { __cvChartHarness: HarnessReport }).__cvChartHarness = report;
