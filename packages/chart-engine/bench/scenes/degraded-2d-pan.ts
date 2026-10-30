// `degraded-2d-pan` scene (E11-T05, README BQ-95): 20 000 bars of up/down cells plus a 40-line
// grid through the batch builder and `Canvas2DBackend` on an injected 2D context, each step a pan
// frame through the shared `ChartViewport` (only the pane block changes). The unit test counts the
// 2D ops (O(buckets), not O(bars)); the .perf.test.ts times the CPU side. The ≥ 30 fps at 20 000
// bars on a real canvas is a per-release manual record (BQ-61's precedent), not a CI gate.
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import type { Ctx2DLike } from "../../src/canvas2d/ctx2d.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import { FrameContext } from "../../src/scene/frame-context.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { INSTANCE_LAYOUTS, PROGRAM } from "../../src/scene/instance-layout.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { PooledBatchSink } from "../../src/scene/pool.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";

const UP = [0.1, 0.7, 0.3, 1] as const;
const DOWN = [0.8, 0.2, 0.2, 1] as const;
const GRID = [0.3, 0.3, 0.3, 1] as const;

/** `n` bar cells (bar i at tick 1000 + i % 50, alternating colour) in the bar-cell layout. */
export function cellRing(n: number): Float32Array {
  const stride = INSTANCE_LAYOUTS[PROGRAM.barCell]?.stride ?? 8;
  const data = new Float32Array(n * stride);
  const ints = new Int32Array(data.buffer);
  for (let i = 0; i < n; i += 1) {
    const at = i * stride;
    ints[at] = i;
    ints[at + 1] = 1000 + (i % 50);
    data.set([0.8, 4, ...(i % 2 === 0 ? UP : DOWN)], at + 2);
  }
  return data;
}

/** `n` horizontal grid lines, 1 px wide, across a 1920 × 1080 store (device px, y up). */
export function gridRing(n: number): Float32Array {
  const stride = INSTANCE_LAYOUTS[PROGRAM.line]?.stride ?? 9;
  const data = new Float32Array(n * stride);
  for (let i = 0; i < n; i += 1) data.set([0, i * 27, 1920, i * 27, 1, ...GRID], i * stride);
  return data;
}

export class Degraded2dPanBench {
  readonly graph = new SceneGraph();
  readonly backend: Canvas2DBackend;
  readonly builder: BatchBuilder;
  readonly viewport = new ChartViewport();
  private readonly uniforms = createPaneUniforms();
  private readonly ctx = new FrameContext();
  private readonly sink = new PooledBatchSink(8);

  constructor(ctx2d: Ctx2DLike, bars = 20_000) {
    this.backend = new Canvas2DBackend(ctx2d);
    this.backend.setPaneUniforms(() => this.uniforms);
    this.backend.setBackground("#101418");
    this.builder = new BatchBuilder(this.graph, this.backend);
    this.graph.addPane("p0");
    const grid = Object.assign(new NullSeries("p0/grid"), { program: PROGRAM.line, count: 40 });
    const cells = Object.assign(new NullSeries("p0/candles"), {
      program: PROGRAM.barCell,
      count: bars,
    });
    this.graph.addNode("p0", "background", grid);
    this.graph.addNode("p0", "series", cells);
    this.backend.attach(grid.id, { data: gridRing(40), head: 0, stride: 9 });
    this.backend.attach(cells.id, { data: cellRing(bars), head: 0, stride: 8 });
    this.viewport.setSize(1920, 1080, 1);
    this.viewport.setPanePlot(0, 0, 1080);
    this.viewport.setPriceRange(0, 990, 1060); // ticks; the transform owns the maths (BQ-71)
  }

  /** One pan frame: the viewport moves `dxPx`, the pane block is rewritten, then submission. */
  step(dxPx = -1): void {
    this.viewport.pan(dxPx);
    this.graph.markViewport();
    this.sink.reset();
    this.ctx.begin(0, 16.7);
    this.graph.frame(this.ctx, this.sink);
    this.builder.build(this.sink);
    writePaneUniforms(this.viewport, 0, this.uniforms);
    this.backend.submit(this.builder.drawList, this.builder.drawCount, 1920, 1080);
  }
}
