// `ribbon-series` scene (E12-S07 PR B): one line, area or baseline series of `n` bars (5k, 100k)
// through the scheduler, the batch builder and `GLBackend` (on the fake GL in tests): a store,
// its CandleRing and the `RibbonSeries`' six hosts over the ring's `RibbonSource` (one buffer).
// Each step is a pan frame (TRANSFORM: uniforms only, B follows the first visible close) or a
// feed frame (one new bar appended, then the frame: one slot uploaded). The unit test counts
// draws (line 3, area 4, baseline 6), uploads and allocations; ribbon-series.perf.test.ts
// times the frames.
import { GLBackend } from "../../src/gl/backend.js";
import type { GL2Like } from "../../src/gl/gl-types.js";
import type { BatchUniforms } from "../../src/gl/submit.js";
import { CandleRing } from "../../src/layers/candle/ring.js";
import { RIBBON_ATTRIBUTES } from "../../src/gl/shaders/ribbon.js";
import { type RibbonKind, RibbonSeries } from "../../src/layers/ribbon/series.js";
import { type BarBatch, BarStore } from "../../src/model/BarStore.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import type { FrameCallback } from "../../src/scene/frame-clock.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { candleBars } from "./candle-series.js";

const THEME = {
  "color.candle.up": "#26a69a",
  "color.candle.down": "#ef5350",
  "color.candle.wick": "#787b86",
  "color.surface.canvas": "#131722",
  "color.chart.line": "#8b5cf6",
};
const W = 1600;
const H = 900;

export class RibbonSeriesBench {
  readonly graph = new SceneGraph();
  readonly store = new BarStore();
  readonly ring: CandleRing;
  readonly series: RibbonSeries;
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
    kind: RibbonKind = "line",
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
    this.series = new RibbonSeries(this.ring, kind);
    const deps = { viewport: this.viewport, pane: 0, theme: () => this.theme };
    const blocks = new Map<string, BatchUniforms>();
    this.series.mount(this.graph, "main", `series.${kind}.0.0`, deps).forEach((h, p) => {
      blocks.set(h.id, this.series.blocks[p] as BatchUniforms);
      this.backend.attach(h.id, this.series.source, RIBBON_ATTRIBUTES);
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
        this.series.frame(vp.barSpacing, vp.dpr, first, vp.plotWidth, H);
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
    const from = window > 0 ? n - window : 0; // all bars at the spacing floor (L2)
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

  /** A feed frame: one new bar appended (one slot), then the frame. */
  feed(t: number): void {
    const { store, ring, live } = this;
    this.next += 60e6;
    live.time[0] = this.next;
    live.close[0] = 1_000 + (t & 3);
    ring.sync(store, store.append(live, true));
    for (const h of this.series.hosts) this.graph.markData(h.id);
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
