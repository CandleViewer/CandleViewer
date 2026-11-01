// `text-batch` scene (E11-S11 PR B, README BQ-275): B3's text sub-gate — 2,500 footprint cells ×
// 2 numbers (12,500 glyphs, two and three digits alternating) written from their cached runs into
// the cell-text batch (the outline program) each pan frame, then built and submitted through
// `GLBackend` on an injected GL. Gated: <= 2.0 ms CPU, <= 2 draws, 0 allocations once warm.
import { GLBackend } from "../../src/gl/backend.js";
import type { GL2Like } from "../../src/gl/gl-types.js";
import { RangeSlot } from "../../src/model/counters.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import { FrameContext } from "../../src/scene/frame-context.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { PooledBatchSink } from "../../src/scene/pool.js";
import { AtlasMetrics } from "../../src/text/glyph-runs.js";
import { TextBatch, type TextInk } from "../../src/text/text-batch.js";
import { buildAtlas } from "./atlas-build.js";

const COLS = 50;
const W = 1920;
const H = 1080;

export class TextBatchBench {
  readonly graph = new SceneGraph();
  readonly backend: GLBackend;
  readonly builder: BatchBuilder;
  readonly cells = new TextBatch("p0/cell-text", PROGRAM.sdfTextOutline);
  readonly metrics = new AtlasMetrics(buildAtlas());
  readonly labels: string[] = [];
  private readonly ctx = new FrameContext();
  private readonly sink = new PooledBatchSink(8);
  private readonly range = new RangeSlot();
  private readonly ink: TextInk = { rgba: Float32Array.of(0.9, 0.92, 0.93, 1), css: "#e8eaed" };
  private x = 0;
  private warm = 0;

  constructor(gl: GL2Like, cells = 2_500) {
    this.backend = new GLBackend(gl, "fake renderer");
    this.builder = new BatchBuilder(this.graph, this.backend);
    this.backend.uploadAtlas(this.metrics.image);
    this.graph.addPane("p0");
    this.graph.addNode("p0", "series", this.cells);
    this.backend.attach(this.cells.id, this.cells);
    this.cells.mode = "glyphs";
    this.cells.metrics = this.metrics;
    for (let i = 0; i < 2 * cells; i += 1)
      this.labels.push(`${i % 2 === 0 ? 10 + (i % 90) : 100 + (i % 900)}`);
    this.step();
    this.warm = this.allocations();
  }

  /** One pan frame: every cell's two numbers at their new place, then collect, build, submit. */
  step(dx = 3): void {
    const t = this.cells;
    this.x = (this.x + dx) % 40;
    t.begin(1, H);
    const n = this.labels.length;
    for (let i = 0; i < n; i += 2) {
      const c = i >> 1;
      const x = this.x + (c % COLS) * (W / COLS);
      const y = 20 + Math.floor(c / COLS) * 20;
      t.label(this.labels[i] as string, x + 2, y, 0, 0, this.ink);
      t.label(this.labels[i + 1] as string, x + 36, y, 0, 1, this.ink);
    }
    this.graph.markData(t.id);
    this.builder.patch(t.id, this.range.set("replace", 0, t.count, 0));
    this.sink.reset();
    this.ctx.begin(0, 16.7);
    this.graph.frame(this.ctx, this.sink);
    this.builder.build(this.sink);
    this.backend.submit(this.builder.drawList, this.builder.drawCount, W, H);
  }

  /** Run misses, ring growth, pool objects and walk rebuilds since warm-up: must be 0. */
  get allocationsInFramePath(): number {
    return this.allocations() - this.warm;
  }

  private allocations(): number {
    const c = this.metrics.counters;
    return c.runMisses + this.cells.grown + this.builder.pool.created + this.graph.rebuilds;
  }
}
