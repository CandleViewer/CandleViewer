// `pan-zero-upload` scene (E11-S01 PR3, B1-like): 100 000 bars in a `BarStore`, one candle node,
// each step a pan frame through the scheduler and the batch builder on a counting upload sink (the
// bufferSubData stand-in until E11-S02, BQ-S12). The unit test counts; the .perf.test.ts times.
import { type BarBatch, BarStore } from "../../src/model/BarStore.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import { Dirty } from "../../src/scene/dirty.js";
import type { FrameCallback } from "../../src/scene/frame-clock.js";
import { FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";

/** `n` one-minute bars from `t0` µs: a static feed, so a pan changes no data. */
export function bars(n: number, t0 = 0): BarBatch {
  const open = Int32Array.from({ length: n }, (_, i) => 1_000 + (i % 50));
  const time = Float64Array.from({ length: n }, (_, i) => t0 + i * 60e6);
  const volume = new Float32Array(n).fill(1);
  return { time, open, high: open, low: open, close: open, volume, priceOrigin: 0, tickSize: 1 };
}

export class PanZeroUploadBench {
  readonly graph = new SceneGraph();
  readonly store = new BarStore();
  readonly series = new NullSeries("candles");
  readonly builder: BatchBuilder;
  readonly scheduler: FrameScheduler;
  dataDirtyCollects = 0; // collects that saw DATA: a pan must make none
  transformCollects = 0;
  requests = 0;
  private pending: FrameCallback | null = null;
  private readonly warm: number;

  constructor(
    n = 100_000,
    private readonly now: () => number = () => 0,
  ) {
    this.graph.addPane("p0");
    this.graph.addNode("p0", "series", this.series);
    this.builder = new BatchBuilder(this.graph, { uploadSubRange: () => undefined }); // counted
    const clock = {
      now: (): number => this.now(),
      requestFrame: (cb: FrameCallback): number => {
        this.pending = cb;
        return (this.requests += 1);
      },
      cancel: (): null => (this.pending = null),
    };
    this.scheduler = new FrameScheduler(this.graph, clock, {
      build: (sink) => this.builder.build(sink),
    });
    this.series.count = this.store.append(bars(n)).to; // the static feed, before the first frame
    this.step(0); // warm-up: the batch's one full upload, the walk build
    this.warm = this.allocations();
    this.dataDirtyCollects = this.transformCollects = 0; // a new node is DIRTY_ALL once
  }

  /** One pan frame: the input router marks the viewport (TRANSFORM) and rAF fires. */
  step(tMs: number): void {
    this.graph.markViewport();
    this.scheduler.wake();
    const frame = this.pending;
    this.pending = null;
    frame?.(tMs);
    const flags = this.series.lastFlags;
    if (flags & Dirty.DATA) this.dataDirtyCollects += 1;
    if (flags & Dirty.TRANSFORM) this.transformCollects += 1;
  }

  /** Pool objects, retained batches, walk rebuilds and queue growth since warm-up: must be 0. */
  get allocationsInFramePath(): number {
    return this.allocations() - this.warm;
  }

  private allocations(): number {
    const { sink, queue } = this.scheduler;
    return sink.pool.created + this.builder.pool.created + this.graph.rebuilds + queue.grown;
  }
}
