// `crosshair-sweep` scene (E11-S07, BQ-6): one chart's crosshair swept across a 1920 × 1080 plot
// at DPR 2 at 1000 px/s (16.7 px a 60 Hz frame) over 5 000 1 m bars, with the weak magnet on.
// Each step is the runtime's per-frame crosshair work: resolve the pointer (bar centre, magnet),
// rewrite the dashed lines (the CPU dash cost, ~375 instances), rebuild the readout when the bar
// moved, and format the posted price and time text. The ticket's budget is ≤ 0.3 ms a frame; the
// .perf.test.ts times it, the counted test checks the work. `dash()` times the line rewrite alone.
// `key()` (E11-S07 BQ-7): a held `→` with the chart root focused, one step a frame: the cursor
// step and its edge follow, the D10 column with the lines, the readout and the spoken summary.
import {
  clockText,
  createZoned,
  dateText,
  decimalsOf,
  formatNumber,
  ZoneClock,
} from "../../src/axes/format.js";
import {
  applyStep,
  createCrosshair,
  createStepResult,
  resolvePointer,
  STEP,
  stepCursor,
  takeBarEdge,
  type MagnetMode,
} from "../../src/overlays/crosshair.js";
import { CROSSHAIR_NODE_ID, CrosshairNode } from "../../src/overlays/crosshair-node.js";
import { Readout, type BarSource } from "../../src/overlays/readout.js";
import { ChartViewport, columnSource, AutoScaler, timeAt } from "../../src/viewport/index.js";

const W = 1920;
const H = 1080;
const DPR = 2;
const GUTTER = 64;
const PLOT = [0, 0, W - GUTTER, H - 24] as const;
/** 1000 px/s at 60 Hz. */
export const PX_PER_FRAME = 1000 / 60;
const THEME = {
  "color.crosshair": "#848e9c",
  "opacity.muted": "0.7",
  "color.focus.ring": "#f0b90b",
  "color.chart.background": "#0b0e11",
};
const MIN = 60e6;
/** The held key's first bar (far from both loaded ends). */
const KEY_START = 1_000;

/** `n` 1 m bars as columns: a slow wave with a 40-tick range per bar. */
export function sweepBars(n: number): BarSource {
  const open = new Int32Array(n);
  const close = new Int32Array(n);
  const high = new Int32Array(n);
  const low = new Int32Array(n);
  const time = new Float64Array(n);
  const volume = new Float32Array(n);
  const delta = new Float32Array(n);
  for (let i = 0; i < n; i += 1) {
    const mid = 128_000 + Math.round(400 * Math.sin(i / 40));
    open[i] = mid - 10;
    close[i] = mid + ((i % 3) - 1) * 12;
    high[i] = mid + 20;
    low[i] = mid - 20;
    time[i] = 1_790_000_000_000_000 + i * MIN;
    volume[i] = 1 + (i % 17) * 0.125;
    delta[i] = (i % 9) - 4;
  }
  return { time, open, high, low, close, volume, delta, priceOrigin: 0, tickSize: 0.5, length: n };
}

export class CrosshairSweepBench {
  readonly viewport: ChartViewport;
  readonly bars: BarSource;
  readonly state = createCrosshair();
  readonly node = new CrosshairNode(CROSSHAIR_NODE_ID);
  readonly readout = new Readout("UTC");
  /** Bar edges (the public event) and readout rebuilds over the run. */
  edges = 0;
  posted = 0;
  /** The last formatted text (kept so the work is not dead code). */
  text = "";
  /** Key steps that moved the view (the edge follow) and the last spoken summary. */
  follows = 0;
  said = "";
  private readonly stepOut = createStepResult();
  private turn = 0;
  private readonly clock = new ZoneClock("UTC");
  private readonly zoned = createZoned();

  constructor(
    n = 5_000,
    readonly magnet: MagnetMode = "weak",
  ) {
    this.bars = sweepBars(n);
    const b = this.bars;
    const map = {
      length: n,
      barDurationUs: MIN,
      indexToTime: (i: number) => (i >= 0 && i < n ? (b.time[i] as number) : Number.NaN),
      timeToIndex: (t: number) => Math.min(n - 1, Math.floor((t - (b.time[0] as number)) / MIN)),
    };
    this.viewport = new ChartViewport(map);
    this.viewport.setSize(PLOT[2], PLOT[3], DPR);
    this.viewport.setPanePlot(0, 0, PLOT[3]);
    this.viewport.setPriceInfo(0, 0, 0.5);
    this.viewport.scrollTo(n - 300, 6);
    new AutoScaler(this.viewport, () => [columnSource(() => b)]).update();
  }

  /** One frame: the pointer 16.7 px further right (wrapping), its y on a slow wave. */
  step(): void {
    this.turn += 1;
    const x = (this.turn * PX_PER_FRAME) % PLOT[2];
    const y = PLOT[3] / 2 + (PLOT[3] / 3) * Math.sin(this.turn / 30);
    const s = this.state;
    const vp = this.viewport;
    resolvePointer(s, vp, 0, this.bars, x, y, this.magnet);
    this.node.write(THEME, DPR, H * DPR, PLOT, s.visible, s.x, s.y, Number.NaN);
    if (takeBarEdge(s)) this.edges += 1;
    if (this.readout.build(this.bars, s.bar, s.snap)) this.posted += 1;
    // The posted message's text, as `postCrosshair` formats it.
    const time = timeAt(vp.map, s.bar);
    const z = this.clock.fields(time / 1000, this.zoned);
    this.text = `${formatNumber(s.tick * 0.5, decimalsOf(0.5))} ${dateText(z)} ${clockText(z.ms, false)}`;
  }

  /**
   * One held-`→` frame (BQ-7) with the root focused, at the worst case: the cursor starts on the
   * last visible bar (bar 1 000), so every step makes the view follow. Then the column and lines,
   * the readout and the spoken summary.
   */
  key(): void {
    const s = this.state;
    const vp = this.viewport;
    const b = this.bars;
    if (s.driver !== "key") {
      vp.scrollTo(KEY_START + 1 - vp.plotWidth / vp.barSpacing);
      s.bar = KEY_START;
      s.tick = b.close[KEY_START] ?? 0;
    }
    const r = stepCursor(vp, b.length, s.bar, s.tick, STEP.barNext, 1, this.stepOut);
    if (r.follow !== 0 && vp.scrollTo(vp.leftIndex + r.follow)) this.follows += 1;
    applyStep(s, vp, 0, r);
    this.node.write(THEME, DPR, H * DPR, PLOT, true, s.x, s.y, Number.NaN, s.x);
    if (takeBarEdge(s)) this.edges += 1;
    if (this.readout.build(b, s.bar, s.snap)) this.posted += 1;
    this.said = r.edge === 0 ? this.readout.full : `${this.readout.full}, last bar`;
  }

  /** The line rewrite alone: the CPU dash cost of a moving cursor. */
  dash(): void {
    this.turn += 1;
    const x = (this.turn * PX_PER_FRAME) % PLOT[2];
    this.node.write(THEME, DPR, H * DPR, PLOT, true, x, (this.turn * 7) % PLOT[3], Number.NaN);
  }
}
