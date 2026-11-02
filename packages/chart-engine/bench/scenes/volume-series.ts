// `volume-series` scene (E12-S08 PR 1, BQ-13; rule 31: a new layer adds a scene): one volume
// series over a store of `n` bars (5k, 100k) through the scheduler, the batch builder and
// `GLBackend` (on the fake GL in tests): the `volume` program, one draw labelled
// `series.volume.body` (the `series.volume` stat), far under the 40-draw ceiling. A pan frame
// uploads nothing; a feed frame (a merged live-bar patch and one new bar) uploads the two touched
// bars once. The unit test counts draws, uploads and allocations; the timing is `volume-ring`'s.
import { GLBackend } from "../../src/gl/backend.js";
import type { GL2Like } from "../../src/gl/gl-types.js";
import { VOLUME_ATTRIBUTES, VolumeSeries } from "../../src/layers/volume/series.js";
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
const W = 1600;
const H = 240;

function volumeBars(n: number, t0 = 0): BarBatch {
  const open = Int32Array.from({ length: n }, (_, i) => 1_000 + (i % 50));
  return {
    time: Float64Array.from({ length: n }, (_, i) => t0 + i * 60e6),
    open,
    high: open.map((o) => o + 4),
    low: open.map((o) => o - 3),
    close: open.map((o, i) => o + ((i % 3) - 1)), // up, doji, down
    volume: Float32Array.from({ length: n }, (_, i) => 1 + (i % 97) * 0.25),
    flags: new Uint8Array(n),
    priceOrigin: 0,
    tickSize: 1,
  };
}

export class VolumeSeriesBench {
  readonly graph = new SceneGraph();
  readonly store = new BarStore();
  readonly series: VolumeSeries;
  readonly builder: BatchBuilder;
  readonly scheduler: FrameScheduler;
  readonly viewport: ChartViewport;
  readonly backend: GLBackend;
  private readonly uniforms = createPaneUniforms();
  private readonly live = volumeBars(1);
  private next: number;
  private pending: FrameCallback | null = null;
  private readonly warm: number;

  constructor(n: number, gl: GL2Like) {
    this.graph.addPane("main");
    this.viewport = new ChartViewport(this.store);
    this.viewport.setSize(W, H, 1);
    this.viewport.setPanePlot(0, 0, H);
    this.backend = new GLBackend(gl, null);
    this.backend.setPaneUniforms(() => this.uniforms);
    this.builder = new BatchBuilder(this.graph, this.backend);
    this.series = new VolumeSeries(0.25, this.builder);
    const theme = { palette: "default" as const, convention: "standard" as const, colors: THEME };
    const host = this.series.mount(this.graph, "main", "series.volume.0", {
      viewport: this.viewport,
      pane: 0,
      theme: () => theme,
    });
    this.backend.attach(host.id, this.series.source, VOLUME_ATTRIBUTES);
    this.backend.setBatchUniforms((b) => (b.nodeId === host.id ? this.series.block : null));
    this.series.setTheme(THEME);
    const clock = {
      now: (): number => 0,
      requestFrame: (cb: FrameCallback): number => ((this.pending = cb), 1),
      cancel: (): null => (this.pending = null),
    };
    this.scheduler = new FrameScheduler(this.graph, clock, {
      build: (sink) => this.builder.build(sink),
      submit: () => {
        this.series.frame(this.viewport.barSpacing, this.viewport.dpr);
        writePaneUniforms(this.viewport, 0, this.uniforms);
        this.uniforms.floats[4] = W;
        this.uniforms.floats[5] = H;
        this.backend.submit(this.builder.drawList, this.builder.drawCount, W, H);
      },
      viewport: this.viewport,
    });
    this.series.sync(this.store, this.store.replace(volumeBars(n)));
    this.viewport.setPriceInfo(0, 0, 1);
    this.viewport.setTimeRange(0, (n - 1) * 60e6);
    this.next = (n - 1) * 60e6;
    this.frame(0);
    this.feed(16); // warm-up: the first eviction-free append and its sub-upload
    this.warm = this.allocations();
  }

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
    const { store, series, live } = this;
    live.time[0] = this.next;
    live.volume[0] = 1 + (t & 7);
    series.sync(store, store.append(live, true));
    this.next += 60e6;
    live.time[0] = this.next;
    series.sync(store, store.append(live, true));
    if (series.host !== null) this.graph.markData(series.host.id);
    this.frame(t);
  }

  /** Objects made past warm-up: batches, GL objects, ring arrays. Must stay 0. */
  allocations(): number {
    const { sink, queue } = this.scheduler;
    const gl = this.backend.registry.stats.created + this.series.ring.rewrites;
    return sink.pool.created + this.builder.pool.created + this.graph.rebuilds + queue.grown + gl;
  }

  get allocationsSinceWarm(): number {
    return this.allocations() - this.warm;
  }
}
