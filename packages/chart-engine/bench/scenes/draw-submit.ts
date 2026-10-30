// `draw-submit` scene (E11-S02 PR2, B5-like): a 3-pane chart (grid, stub candles, two indicator
// lines, crosshair, axis labels per pane) through the batch builder and `GLBackend` on an injected
// GL, each step a pan frame. The draw-call gate reads its trace (README BQ-51); the .perf.test.ts
// times submission against 06 §4.3's composite + present slice (<= 1.6 ms).
import { GLBackend } from "../../src/gl/backend.js";
import type { GL2Like } from "../../src/gl/gl-types.js";
import { PROGRAM } from "../../src/gl/program-cache.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import type { LayerName } from "../../src/scene/dirty.js";
import { FrameContext } from "../../src/scene/frame-context.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { PooledBatchSink } from "../../src/scene/pool.js";

/** Per pane: [node, layer, program, texture, instances]; texture 1 is the SDF atlas. */
const PANE: readonly (readonly [string, LayerName, number, number, number])[] = [
  ["grid", "background", PROGRAM.line, 0, 40],
  ["candles", "series", PROGRAM.barCell, 0, 500],
  ["ema", "overlays", PROGRAM.line, 0, 499],
  ["vwap", "overlays", PROGRAM.line, 0, 499],
  ["crosshair", "foreground", PROGRAM.line, 0, 2],
  ["labels", "foreground", PROGRAM.sdfText, 1, 64],
];
const STRIDE = 4;

export class DrawSubmitBench {
  readonly graph = new SceneGraph();
  readonly backend: GLBackend;
  readonly builder: BatchBuilder;
  readonly nodes: NullSeries[] = [];
  private readonly ctx = new FrameContext();
  private readonly sink = new PooledBatchSink(32);

  /** `bars`: the candles ring's slots (context-restore rebuilds 100 000). */
  constructor(gl: GL2Like, panes = 3, bars = 1024) {
    this.backend = new GLBackend(gl, "fake renderer");
    this.builder = new BatchBuilder(this.graph, this.backend);
    this.backend.textures.define(1, 256, 256, null);
    for (let p = 0; p < panes; p += 1) {
      this.graph.addPane(`p${p}`);
      for (const [name, layer, program, texture, count] of PANE) {
        const node = Object.assign(new NullSeries(`p${p}/${name}`), { program, texture, count });
        this.graph.addNode(`p${p}`, layer, node);
        const data = new Float32Array((name === "candles" ? bars : 1024) * STRIDE);
        this.backend.buffers.attach(node.id, { data, head: 0, stride: STRIDE });
        this.nodes.push(node);
      }
    }
  }

  /** One pan frame: collect, build, submit. */
  step(): void {
    this.graph.markViewport();
    this.sink.reset();
    this.ctx.begin(0, 16.7);
    this.graph.frame(this.ctx, this.sink);
    this.builder.build(this.sink);
    this.backend.submit(this.builder.drawList, this.builder.drawCount, 1920, 1080);
  }
}
