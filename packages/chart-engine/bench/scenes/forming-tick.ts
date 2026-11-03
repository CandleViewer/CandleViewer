// `forming-tick` scene (E12-S10): the live forming bar of a candle series of `n` bars (5k, 100k),
// 120 in view (L0, so its dashed ring draws), through the scheduler, the batch builder and
// `GLBackend` (the fake GL in tests). Each tick merges a new close into the forming bar (equal
// time, inside its high / low and keeping its direction, as most trades do): the store patches
// one slot, the ring writes one 20-byte instance, the marks entry ([slot, high, low, open, kind])
// is unchanged and uploads nothing. `confirm` closes the bar (the forming bit cleared, one slot)
// and opens the next. It reads no clock: forming-tick.test.ts asserts the bytes, uploads, draws
// and allocations; forming-tick.perf.test.ts times the ticks.
import type { GL2Like } from "../../src/gl/gl-types.js";
import { BAR_FLAG, type BarBatch } from "../../src/model/BarStore.js";
import { CandleSeriesBench, candleBars } from "./candle-series.js";

const STEP_US = 60e6;

export class FormingTickBench {
  readonly scene: CandleSeriesBench;
  /** Bar state events the runtime would post (drained per mutation, as `storeBars` does). */
  events = 0;
  private readonly live: BarBatch = candleBars(1);
  private time: number;
  private readonly marksData: Float32Array;
  private readonly warm: number;

  constructor(n: number, gl: GL2Like, now: () => number = () => 0, window = 120) {
    this.scene = new CandleSeriesBench(n, gl, now, "candles", window);
    const { store, viewport, graph } = this.scene;
    this.time = store.indexToTime(store.length - 1);
    viewport.setTimeRange(this.time - (window - 1) * STEP_US, this.time); // the live edge in view
    graph.markViewport();
    const flags = this.live.flags as Uint8Array;
    flags[0] = BAR_FLAG.forming; // the last bar starts forming: its mark and its one event
    this.live.time[0] = this.time;
    this.scene.tick(32, this.live);
    this.drain();
    this.tick(48); // warm-up: the first steady tick
    this.marksData = this.scene.series.marks.data;
    this.warm = this.scene.allocations();
  }

  /** One trade: the forming bar's close moves inside its range, keeping its direction. */
  tick(t: number): void {
    const live = this.live;
    live.time[0] = this.time;
    live.close[0] = (live.low[0] as number) + ((t >> 4) % 3); // 997..999: a down bar throughout
    this.scene.tick(t, live);
    this.drain();
  }

  /** The bar closes (`confirm`: the forming bit cleared, one slot) and the next one opens. */
  confirm(t: number): void {
    const live = this.live;
    const flags = live.flags as Uint8Array;
    flags[0] = 0;
    this.scene.tick(t, live);
    this.drain();
    this.time += STEP_US;
    live.time[0] = this.time;
    flags[0] = BAR_FLAG.forming;
    this.scene.tick(t + 1, live);
    this.drain();
  }

  private drain(): void {
    this.events += this.scene.series.marks.takeEvents();
  }

  /** Objects made past warm-up (the scene's, plus a reallocated marks buffer): must stay 0. */
  get allocationsSinceWarm(): number {
    const marks = this.scene.series.marks.data === this.marksData ? 0 : 1;
    return this.scene.allocations() - this.warm + marks;
  }
}
