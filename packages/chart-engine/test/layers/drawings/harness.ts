// The 2D harness and the float32 shader stand-in the drawings tests share (E14-T03 slices 2-3):
// one pane, a `DrawingsNode` and its fill node on a Canvas 2D backend over the pane block, and the
// vertex shaders' `project()` emulated with Math.fround (BQ-78's CPU stand-in until E11-T08).
import { Canvas2DBackend } from "../../../src/canvas2d/backend.js";
import type { DrawingInput } from "../../../src/layers/drawings/model.js";
import { DrawingsNode } from "../../../src/layers/drawings/project.js";
import type { InstanceRing } from "../../../src/layers/drawings/ring.js";
import { BatchBuilder } from "../../../src/scene/batch-builder.js";
import { FrameContext } from "../../../src/scene/frame-context.js";
import { SceneGraph } from "../../../src/scene/graph.js";
import { PooledBatchSink } from "../../../src/scene/pool.js";
import * as tf from "../../../src/viewport/index.js";
import { FakeCtx2D } from "../../canvas2d/fake-ctx2d.js";
import { minuteMap } from "../../interaction/fixtures.js";

/** A 2D context that also records caps and dashes. */
export class DashCtx extends FakeCtx2D {
  lineCap = "butt";
  readonly dashes: number[][] = [];
  /** Every `ellipse` call as `x y rx ry`, in order. */
  readonly ellipses: number[][] = [];
  setLineDash(s: readonly number[]): void {
    this.dashes.push([...s]);
  }
  ellipse(x: number, y: number, rx: number, ry: number): void {
    this.ellipses.push([x, y, rx, ry]);
  }
}

const fr = Math.fround;
/** The vertex shader's `project()` in float32 on the real block and ring: device px, y down. */
export function standIn(
  ring: InstanceRing,
  at: number,
  k: number,
  b: tf.PaneUniforms,
): [number, number] {
  const [i, f, u] = [ring.ints, ring.data, b.floats];
  const o = at * ring.stride + 4 * k; // ivec4 <k>: ints, then intBitsToFloat of the fractions
  const rx = fr(fr((i[o] ?? 0) - (b.ints[0] ?? 0)) + (f[o + 2] ?? 0));
  const ry = fr(fr((i[o + 1] ?? 0) - (b.ints[1] ?? 0)) + (f[o + 3] ?? 0));
  const x = fr(fr(fr(rx + 0.5) - (u[3] ?? 0)) * (u[0] ?? 0));
  const r = fr(Math.max(fr(ry * (u[6] ?? 0)), fr(-0.999999)));
  const l =
    Math.abs(r) <= 0.05 ? fr(r * (1 - r * (0.5 - r * (0.33333333 - r * 0.25)))) : fr(Math.log1p(r));
  const y = fr(fr(fr(ry * (1 - (u[7] ?? 0))) + fr(l * (u[7] ?? 0))) * (u[1] ?? 0)) + (u[2] ?? 0);
  return [x, fr(y)];
}

/** Where the view sits: its bar map, left index and price window (ticks). */
interface At {
  readonly map?: tf.IndexTimeMap;
  readonly left?: number;
  readonly low?: number;
  readonly high?: number;
}

export function harness(dpr: number, log: boolean, drawings: DrawingInput[], at: At = {}) {
  const vp = new tf.ChartViewport(at.map ?? minuteMap());
  vp.setSize(1200, 700, dpr);
  vp.setPanePlot(0, 0, 700);
  vp.setPriceInfo(0, 0, 0.5);
  (vp.panes[0] as tf.PaneTransform).logReason = null;
  vp.setScale(0, { mode: log ? "log" : "linear" });
  vp.setPriceRange(0, at.low ?? 990, at.high ?? 1_060);
  vp.scrollTo(at.left ?? 0);
  const graph = new SceneGraph();
  graph.addPane("p0");
  const node = new DrawingsNode("p0/drawings/set");
  graph.addNode("p0", "drawings", node);
  graph.addNode("p0", "drawings", node.fillNode);
  const ctx2d = new DashCtx();
  const backend = new Canvas2DBackend(ctx2d);
  const builder = new BatchBuilder(graph, backend);
  const block = tf.createPaneUniforms();
  backend.attach(node.id, node.lines);
  backend.attach(node.fillNode.id, node.fills);
  backend.setPaneUniforms(() => block);
  node.apply({ op: "replace", drawings });
  const fctx = new FrameContext(vp);
  const sink = new PooledBatchSink();
  const frame = (): void => {
    sink.reset();
    fctx.begin(0, 16);
    graph.frame(fctx, sink);
    builder.build(sink);
    tf.writePaneUniforms(vp, 0, block);
    ctx2d.paths.length = ctx2d.dashes.length = ctx2d.ellipses.length = 0;
    backend.submit(builder.drawList, builder.drawCount, vp.plotWidth * dpr, vp.height * dpr);
  };
  frame();
  return { vp, graph, node, ctx2d, block, frame, backend, builder };
}

export const nums = (part: string): number[] => part.split(" ").slice(1).map(Number);
