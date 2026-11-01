// `drawings-drag` scene (E14-T03, the B8 skeleton; R5): 100 000 bars, 200 seeded drawings plus 50
// order lines (hlines) in the drawings layer, with candle and footprint stand-ins in the series and
// overlays layers. Slice 2: the frame runs the batch builder and, given one, a real backend (the
// GL fake or Canvas 2D) on the pane block, so the `drawing-line` and (slice 3) `drawing-fill`
// batches' uploads and draws count.
// `run` drags one segment for 180 frames (a `patch`, then a frame); `pan` is TRANSFORM only. The
// unit tests count; slice T03-f adds the timed half (B8 ≤ 12 ms).
import { mulberry32 } from "../fixtures/rng.mjs";
import type { RenderBackend } from "../../src/gl/backend.js";
import { BarStore } from "../../src/model/BarStore.js";
import type { DrawingInput, DrawingKind, SetDrawings } from "../../src/layers/drawings/model.js";
import { FILL_ATTRIBUTES } from "../../src/layers/drawings/fills.js";
import { LINE_ATTRIBUTES } from "../../src/layers/drawings/lines.js";
import { DrawingsNode } from "../../src/layers/drawings/project.js";
import { BatchBuilder } from "../../src/scene/batch-builder.js";
import { FrameContext } from "../../src/scene/frame-context.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { PooledBatchSink } from "../../src/scene/pool.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { bars } from "./pan-zero-upload.js";

const KINDS: readonly DrawingKind[] = [
  ...["segment", "ray", "line", "polyline"],
  ...["rect", "ellipse", "band", "text"],
] as DrawingKind[];
const US = 60e6; // one bar
const style = { colour: 0x2962ffff, width: 2, dash: 0 } as const;
export const DRAG_FRAMES = 180; // 3 s at 60 fps (Scenario 1)
/**
 * Line instances seeded: 25 each of segment, ray, line and two-point polyline, 25 rects × 4 and
 * 25 bands × 2 edges, + 50 hlines; fill instances: the 25 each of rect, band and ellipse.
 */
export const LINE_INSTANCES = 300;
export const FILL_INSTANCES = 75;
export const PLOT = { width: 1920, height: 1080 };

export class DrawingsDragBench {
  readonly graph = new SceneGraph();
  readonly viewport: ChartViewport;
  readonly drawings = new DrawingsNode("p0/drawings/set");
  readonly price = new NullSeries("candles");
  readonly footprint = new NullSeries("footprint");
  readonly builder: BatchBuilder;
  readonly uniforms = createPaneUniforms();
  private readonly ctx: FrameContext;
  private readonly sink = new PooledBatchSink();
  private readonly drags: SetDrawings[] = [];
  private t = 0;

  constructor(
    n = 100_000,
    seed = 358,
    readonly backend: RenderBackend | null = null,
    dpr = 1,
  ) {
    const store = new BarStore({ maxBars: n });
    store.append(bars(n));
    this.viewport = new ChartViewport(store);
    this.viewport.setSize(PLOT.width, PLOT.height, dpr);
    this.viewport.setPanePlot(0, 0, PLOT.height);
    this.viewport.setPriceRange(0, 990, 1_060);
    this.viewport.scrollTo(n - 200);
    this.graph.addPane("p0");
    this.graph.addNode("p0", "series", this.price);
    this.graph.addNode("p0", "overlays", this.footprint);
    this.graph.addNode("p0", "drawings", this.drawings);
    this.graph.addNode("p0", "drawings", this.drawings.fillNode);
    this.ctx = new FrameContext(this.viewport);
    this.builder = new BatchBuilder(this.graph, backend ?? { uploadSubRange: () => undefined });
    this.drawings.onRange = (id, r) => this.builder.patch(id, r);
    backend?.attach(this.drawings.id, this.drawings.lines, LINE_ATTRIBUTES);
    backend?.attach(this.drawings.fillNode.id, this.drawings.fills, FILL_ATTRIBUTES);
    backend?.setPaneUniforms(() => this.uniforms);
    const rng = mulberry32(seed);
    const at = (): number[] => [(n - 200 + rng() * 200) * US, 1_000 + Math.round(rng() * 50)];
    const drawings: DrawingInput[] = [];
    for (let i = 0; i < 250; i += 1) {
      const kind = i < 200 ? (KINDS[i % KINDS.length] as DrawingKind) : "hline";
      const k = kind === "text" || kind === "hline" ? 1 : kind === "band" ? 3 : 2;
      const points = Array.from({ length: k }, at).flat();
      const filled = kind === "rect" || kind === "band" || kind === "ellipse";
      const s = { ...style, dash: (i % 3) as 0 | 1 | 2, ...(filled && { fill: 0x2962ff33 }) };
      drawings.push({ id: i < 200 ? `d${i}` : `o${i}`, kind, points, style: s });
    }
    this.drawings.apply({ op: "replace", drawings });
    for (let f = 0; f < DRAG_FRAMES; f += 1) {
      const t0 = (n - 150 + f / 10) * US; // the host's messages: built outside the frames
      const points = [t0, 1_010 + (f % 20), t0 + 5 * US, 1_030];
      this.drags.push({ op: "patch", drawings: [{ id: "d8", kind: "segment", points, style }] });
    }
    this.frame();
  }

  /** Collect, build (uploads), the pane block, then the backend's submit. */
  frame(): void {
    this.sink.reset();
    this.ctx.begin((this.t += 16), 16.7);
    this.graph.frame(this.ctx, this.sink);
    this.builder.build(this.sink);
    const vp = this.viewport;
    writePaneUniforms(vp, 0, this.uniforms);
    const w = Math.round(PLOT.width * vp.dpr);
    const h = Math.round(PLOT.height * vp.dpr);
    this.backend?.submit(this.builder.drawList, this.builder.drawCount, w, h);
  }

  run(): void {
    for (const drag of this.drags) {
      this.drawings.apply(drag);
      this.frame();
    }
  }

  pan(dx: number): void {
    this.viewport.pan(dx);
    this.graph.markViewport();
    this.frame();
  }
}
