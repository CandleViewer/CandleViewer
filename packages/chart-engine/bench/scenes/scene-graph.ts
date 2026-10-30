// `scene-graph` microbench (E11-S01): 3 panes x 12 nodes, each step a pan frame (every drawable
// TRANSFORM-dirty) plus one series data update, with zero allocation in the frame path. It reads no
// clock: scene-graph.test.ts asserts the counts, scene-graph.perf.test.ts times it (BQ-24).
import { FrameContext, LAYER_ORDER, PooledBatchSink, SceneGraph } from "../../src/scene/index.js";
import { NullSeries } from "../../src/scene/null-series.js";

export class SceneGraphBench {
  readonly graph = new SceneGraph();
  readonly ctx = new FrameContext();
  readonly sink = new PooledBatchSink(64);
  private readonly series: string[] = [];
  frames = 0;
  collected = 0;
  private readonly warm: number;

  constructor(panes = 3, nodesPerPane = 12) {
    for (let p = 0; p < panes; p += 1) {
      this.graph.addPane(`p${p}`);
      for (let n = 0; n < nodesPerPane; n += 1) {
        const layer = LAYER_ORDER[n % LAYER_ORDER.length] ?? "series";
        this.graph.addNode(`p${p}`, layer, new NullSeries(`p${p}:${n}`, { zIndex: n }));
        if (layer === "series") this.series.push(`p${p}:${n}`);
      }
    }
    this.step(0); // warm-up: the first collect and the one walk build
    this.warm = this.sink.pool.created + this.graph.rebuilds;
  }

  step(tMs: number): void {
    this.graph.markViewport();
    this.graph.markData(this.series[this.frames % this.series.length] ?? "");
    this.sink.reset();
    this.ctx.begin(tMs, 16.7);
    this.graph.frame(this.ctx, this.sink);
    this.collected += this.ctx.stats.collected;
    this.frames += 1;
  }

  /** Pool objects created plus walk rebuilds since warm-up: must stay 0. */
  get allocationsInFramePath(): number {
    return this.sink.pool.created + this.graph.rebuilds - this.warm;
  }
}
