// `drawings-drag` scene (E14-T03 slice 1, the B8 skeleton; R5): 100 000 bars, 200 seeded
// drawings plus 50 order lines (hlines) in the drawings layer, with candle and footprint stand-ins
// in the series and overlays layers. `run` drags one drawing for 180 frames (a `patch`, then a
// scene-graph frame); `pan` runs a TRANSFORM-only frame. The unit test counts; slice T03-f adds
// the timed half (B8 ≤ 12 ms) and the GPU counters once the layer draws.
import { mulberry32 } from "../fixtures/rng.mjs";
import { BarStore } from "../../src/model/BarStore.js";
import type { DrawingInput, DrawingKind, SetDrawings } from "../../src/layers/drawings/model.js";
import { DrawingsNode } from "../../src/layers/drawings/project.js";
import { FrameContext } from "../../src/scene/frame-context.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { NullSeries } from "../../src/scene/null-series.js";
import { PooledBatchSink } from "../../src/scene/pool.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { bars } from "./pan-zero-upload.js";

const KINDS: readonly DrawingKind[] = ["segment", "ray", "rect", "ellipse", "band", "text"];
const US = 60e6; // one bar
const style = { colour: 0x2962ffff, width: 2, dash: 0 } as const;
export const DRAG_FRAMES = 180; // 3 s at 60 fps (Scenario 1)

export class DrawingsDragBench {
  readonly graph = new SceneGraph();
  readonly viewport: ChartViewport;
  readonly drawings = new DrawingsNode("p0/drawings/set");
  readonly price = new NullSeries("candles");
  readonly footprint = new NullSeries("footprint");
  private readonly ctx: FrameContext;
  private readonly sink = new PooledBatchSink();
  private readonly drags: SetDrawings[] = [];
  private t = 0;

  constructor(n = 100_000, seed = 358) {
    const store = new BarStore({ maxBars: n });
    store.append(bars(n));
    this.viewport = new ChartViewport(store);
    this.viewport.setSize(1920, 1080, 1);
    this.viewport.setPanePlot(0, 0, 1080);
    this.viewport.setPriceRange(0, 990, 1_060);
    this.viewport.scrollTo(n - 200);
    this.graph.addPane("p0");
    this.graph.addNode("p0", "series", this.price);
    this.graph.addNode("p0", "overlays", this.footprint);
    this.graph.addNode("p0", "drawings", this.drawings);
    this.ctx = new FrameContext(this.viewport);
    const rng = mulberry32(seed);
    const at = (): number[] => [(n - 200 + rng() * 200) * US, 1_000 + Math.round(rng() * 50)];
    const drawings: DrawingInput[] = [];
    for (let i = 0; i < 250; i += 1) {
      const kind = i < 200 ? (KINDS[i % KINDS.length] as DrawingKind) : "hline";
      const k = kind === "text" || kind === "hline" ? 1 : kind === "band" ? 3 : 2;
      const points = Array.from({ length: k }, at).flat();
      drawings.push({ id: i < 200 ? `d${i}` : `o${i}`, kind, points, style });
    }
    this.drawings.apply({ op: "replace", drawings });
    for (let f = 0; f < DRAG_FRAMES; f += 1) {
      const t0 = (n - 150 + f / 10) * US; // the host's messages: built outside the frames
      const points = [t0, 1_010 + (f % 20), t0 + 5 * US, 1_030];
      this.drags.push({ op: "patch", drawings: [{ id: "d7", kind: "segment", points, style }] });
    }
    this.frame();
  }

  frame(): void {
    this.sink.reset();
    this.ctx.begin((this.t += 16), 16.7);
    this.graph.frame(this.ctx, this.sink);
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
