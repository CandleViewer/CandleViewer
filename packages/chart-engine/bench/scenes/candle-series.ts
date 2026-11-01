// `candle-series` scene (E12-S06): one candle or OHLC series of `n` bars (5k, 100k) through the
// scheduler, the batch builder and `GLBackend` (on the fake GL in tests): a store, its CandleRing,
// the series' two mark hosts sharing one buffer and its seam host. Each step is a pan frame
// (TRANSFORM: uniforms only) or a feed frame (a merged live-bar patch and one new bar, then the
// frame). Candles show every bar at the spacing floor (BQ-13); OHLC rows show `window` bars
// (≈ 13 px: the stem and the 10-vertex ticks) or, without one, the floor's candle mark. The unit
// test counts draws, uploads and allocations; candle-series.perf.test.ts times the frames.
import { GLBackend } from "../../src/gl/backend.js";
import type { GL2Like } from "../../src/gl/gl-types.js";
import { CandleRing } from "../../src/layers/candle/ring.js";
import { BarSeries } from "../../src/layers/candle/bars.js";
import { CANDLE_ATTRIBUTES, CandleSeries } from "../../src/layers/candle/series.js";
import { type BarBatch, BarStore } from "../../src/model/BarStore.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import type { FrameCallback } from "../../src/scene/frame-clock.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";

const THEME = {
  "color.candle.up": "#26a69a",
  "color.candle.down": "#ef5350",
  "color.candle.wick": "#787b86",
  "color.surface.canvas": "#131722",
};
/** The same tokens with up and down swapped: a theme switch (STYLE: uniforms, no upload). */
const SWAPPED = {
  ...THEME,
  "color.candle.up": THEME["color.candle.down"],
  "color.candle.down": THEME["color.candle.up"],
};
const W = 1600;
const H = 900;

/** `n` one-minute bars with a small up / down / doji mix; one batch shape (flags included). */
export function candleBars(n: number, t0 = 0): BarBatch {
  const open = Int32Array.from({ length: n }, (_, i) => 1_000 + (i % 50));
  return {
    time: Float64Array.from({ length: n }, (_, i) => t0 + i * 60e6),
    open,
    high: open.map((o) => o + 4),
    low: open.map((o) => o - 3),
    close: open.map((o, i) => o + ((i % 3) - 1)),
    volume: new Float32Array(n).fill(1),
    flags: new Uint8Array(n),
    priceOrigin: 0,
    tickSize: 1,
  };
}

export class CandleSeriesBench {
  readonly graph = new SceneGraph();
  readonly store = new BarStore();
  readonly ring: CandleRing;
  readonly series: CandleSeries;
  readonly builder: BatchBuilder;
  readonly scheduler: FrameScheduler;
  readonly viewport: ChartViewport;
  readonly backend: GLBackend;
  private readonly uniforms = createPaneUniforms();
  private readonly live: BarBatch = candleBars(1);
  private next: number;
  private pending: FrameCallback | null = null;
  private readonly warm: number;

  constructor(
    n: number,
    gl: GL2Like,
    private readonly now: () => number = () => 0,
    shape: "candles" | "bars" = "candles",
    window = 0,
  ) {
    this.graph.addPane("main");
    this.viewport = new ChartViewport(this.store);
    this.viewport.setSize(W, H, 1);
    this.viewport.setPanePlot(0, 0, H);
    this.backend = new GLBackend(gl, null);
    this.backend.setPaneUniforms(() => this.uniforms);
    this.builder = new BatchBuilder(this.graph, this.backend);
    this.ring = new CandleRing(this.builder);
    this.series = shape === "bars" ? new BarSeries(this.ring) : new CandleSeries(this.ring);
    const deps = { viewport: this.viewport, pane: 0, theme: () => this.theme };
    const blocks = new Map<string, (typeof this.series.blocks)[number]>();
    this.series.mount(this.graph, "main", "series.candle.0.0", deps).forEach((h, p) => {
      blocks.set(h.id, this.series.blocks[p] as (typeof this.series.blocks)[number]);
      this.backend.attach(h.id, this.series.sources[p] ?? this.ring, CANDLE_ATTRIBUTES);
    });
    this.backend.setBatchUniforms((b) => blocks.get(b.nodeId) ?? null);
    this.series.setTheme(THEME);
    const clock = {
      now: (): number => this.now(),
      requestFrame: (cb: FrameCallback): number => ((this.pending = cb), 1),
      cancel: (): null => (this.pending = null),
    };
    this.scheduler = new FrameScheduler(this.graph, clock, {
      build: (sink) => this.builder.build(sink),
      submit: () => {
        const vp = this.viewport;
        const first = Math.floor(vp.leftIndex);
        const last = Math.floor(vp.leftIndex + vp.plotWidth / vp.barSpacing);
        this.series.frame(vp.barSpacing, vp.dpr, first, last);
        writePaneUniforms(this.viewport, 0, this.uniforms);
        this.uniforms.floats[4] = W;
        this.uniforms.floats[5] = H;
        this.backend.submit(this.builder.drawList, this.builder.drawCount, W, H);
      },
      viewport: this.viewport,
    });
    const all = candleBars(n);
    this.ring.sync(this.store, this.store.replace(all));
    this.viewport.setPriceInfo(0, 0, 1);
    const from = window > 0 ? n - window : 0; // all bars at the spacing floor (BQ-13)
    this.viewport.setTimeRange(from * 60e6, (n - 1) * 60e6);
    this.next = (n - 1) * 60e6;
    this.frame(0);
    this.feed(16); // warm-up: the first eviction-free append and its sub-upload
    this.warm = this.allocations();
  }

  private readonly theme = {
    palette: "default" as const,
    convention: "standard" as const,
    colors: THEME,
  };

  private frame(t: number): void {
    this.scheduler.wake();
    const cb = this.pending;
    this.pending = null;
    cb?.(t);
  }

  /** A pan frame: TRANSFORM only. */
  pan(t: number): void {
    this.viewport.pan(t % 32 < 16 ? 3 : -3);
    this.graph.markViewport();
    this.frame(t);
  }

  /** A feed frame: the live bar patched (merge), one new bar appended, then the frame. */
  feed(t: number): void {
    const { store, ring, live } = this;
    live.time[0] = this.next;
    live.close[0] = 1_000 + (t & 3);
    ring.sync(store, store.append(live, true));
    this.next += 60e6;
    live.time[0] = this.next;
    ring.sync(store, store.append(live, true));
    for (const h of this.series.hosts) this.graph.markData(h.id);
    this.frame(t);
  }

  /** A theme switch: the palette re-resolved (theme load), STYLE marked, then the frame. */
  switchTheme(t: number): void {
    this.series.setTheme(t % 32 < 16 ? SWAPPED : THEME);
    this.graph.markTheme();
    this.frame(t);
  }

  /** Objects made past warm-up: batches, GL objects, ring arrays. Must stay 0. */
  allocations(): number {
    const { sink, queue } = this.scheduler;
    const gl = this.backend.registry.stats.created + this.ring.rewrites;
    return sink.pool.created + this.builder.pool.created + this.graph.rebuilds + queue.grown + gl;
  }

  get allocationsSinceWarm(): number {
    return this.allocations() - this.warm;
  }
}
