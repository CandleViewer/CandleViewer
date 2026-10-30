// `scheduler-overhead` microbench (E11-S01 PR2): 3 panes x 12 nodes, each step a pan frame plus a
// queued data mutation through the whole frame, with 06 §4.3's nine stage timings. The unit test
// injects a frozen clock and counts; the .perf.test.ts the wall clock (<= 0.3 ms per frame, BQ-24).
import type { FrameCallback } from "../../src/scene/frame-clock.js";
import { FRAME_STAGES, type FrameStage, FrameScheduler } from "../../src/scene/frame-scheduler.js";
import { LAYER_ORDER, SceneGraph } from "../../src/scene/index.js";
import { NullSeries } from "../../src/scene/null-series.js";

export class SchedulerOverheadBench {
  readonly graph = new SceneGraph();
  readonly scheduler: FrameScheduler;
  readonly stageTotalsMs = new Float64Array(FRAME_STAGES.length);
  requests = 0;
  private pending: FrameCallback | null = null;
  private readonly series: string[] = [];
  private readonly mutation = (): void => {
    this.graph.markData(this.series[this.scheduler.frames % this.series.length] ?? "");
  };
  private readonly warm: number;

  constructor(private readonly now: () => number = () => 0) {
    for (let p = 0; p < 3; p += 1) {
      this.graph.addPane(`p${p}`);
      for (let n = 0; n < 12; n += 1) {
        const layer = LAYER_ORDER[n % LAYER_ORDER.length] ?? "series";
        this.graph.addNode(`p${p}`, layer, new NullSeries(`p${p}:${n}`, { zIndex: n }));
        if (layer === "series") this.series.push(`p${p}:${n}`);
      }
    }
    const clock = {
      now: (): number => this.now(),
      requestFrame: (cb: FrameCallback): number => {
        this.pending = cb;
        return (this.requests += 1);
      },
      cancel: (): void => {
        this.pending = null;
      },
    };
    this.scheduler = new FrameScheduler(this.graph, clock);
    this.step(0); // warm-up: the first collect and the one walk build
    this.warm = this.allocations();
  }

  /** One pan + data frame: the input router marks and the data port enqueues, then rAF fires. */
  step(tMs: number): void {
    this.graph.markViewport();
    this.scheduler.enqueue(this.mutation);
    const frame = this.pending;
    this.pending = null;
    frame?.(tMs);
    const ms = this.scheduler.timings.ms;
    for (let i = 0; i < ms.length; i += 1) {
      this.stageTotalsMs[i] = (this.stageTotalsMs[i] as number) + (ms[i] as number);
    }
  }

  /** Pool objects, walk rebuilds and queue growth since warm-up: must stay 0. */
  get allocationsInFramePath(): number {
    return this.allocations() - this.warm;
  }

  /** The bench report's `perStageMs` shape (bench/scene.mjs): mean ms per frame per stage. */
  perStageMs(): Record<FrameStage, number> {
    const frames = Math.max(1, this.scheduler.frames);
    const entries = FRAME_STAGES.map((s, i) => [s, (this.stageTotalsMs[i] as number) / frames]);
    return Object.fromEntries(entries) as Record<FrameStage, number>;
  }

  private allocations(): number {
    const { sink, queue } = this.scheduler;
    return sink.pool.created + this.graph.rebuilds + queue.grown;
  }
}
