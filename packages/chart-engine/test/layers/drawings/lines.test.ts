// E14-T03 slice 2: the `drawing-line` ring (instance counts, chart-space anchors, width × dpr,
// compare-first change ranges), the dash LUT held equal to the shader's, and the two backends in
// parity at dpr 1, 1.5 and 2: the Canvas 2D painter's path and a float32 stand-in of the vertex
// shader (BQ-78's CPU stand-in until E11-T08's SwiftShader goldens) both put p0 and p1 where the
// shared transform does, the stroke stays 4 CSS px and the dash period 24 CSS px at any zoom.
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../../src/canvas2d/backend.js";
import { DASH_LUT, DRAWING_LINE } from "../../../src/gl/shaders/drawing-line.js";
import { LINE_STRIDE, LineInstances, lineCount } from "../../../src/layers/drawings/lines.js";
import type { DrawingInput } from "../../../src/layers/drawings/model.js";
import { DrawingsNode, reindex, toRecord } from "../../../src/layers/drawings/project.js";
import { BatchBuilder } from "../../../src/scene/batch-builder.js";
import { FrameContext } from "../../../src/scene/frame-context.js";
import { SceneGraph } from "../../../src/scene/graph.js";
import { PROGRAM } from "../../../src/scene/instance-layout.js";
import { NullSeries } from "../../../src/scene/null-series.js";
import { PooledBatchSink } from "../../../src/scene/pool.js";
import * as tf from "../../../src/viewport/index.js";
import { FakeCtx2D } from "../../canvas2d/fake-ctx2d.js";
import { minuteMap } from "../../interaction/fixtures.js";

const T = (i: number): number => minuteMap().indexToTime(i);
const style = { colour: 0x2962ff80, width: 4, dash: 1 } as const;
const input = (kind: DrawingInput["kind"], points: number[], extra = {}): DrawingInput => ({
  ...{ id: kind, kind, points, style },
  ...extra,
});

describe("the drawing-line ring", () => {
  const map = minuteMap();
  const rec = (d: DrawingInput) => {
    const r = toRecord(d);
    reindex(r, map, 1);
    return r;
  };

  it("draws one instance per segment of a visible line-type kind, none for fills or text", () => {
    const counts = [
      input("segment", [T(1), 1, T(2), 2]),
      input("ray", [T(1), 1, T(2), 2]),
      input("line", [T(1), 1, T(2), 2]),
      input("hline", [T(1), 1]),
      input("vline", [T(1), 1]),
      input("polyline", [T(1), 1, T(2), 2, T(3), 1, T(4), 5]),
      input("rect", [T(1), 1, T(2), 2]),
      input("band", [T(1), 1, T(2), 2, T(3), 3]),
      input("text", [T(1), 1]),
      input("segment", [T(1), 1, T(2), 2], { visible: false }),
    ].map((d) => lineCount(rec(d)));
    expect(counts).toEqual([1, 1, 1, 1, 1, 3, 0, 0, 0, 0]);
  });

  it("writes each anchor as an ivec4, width × dpr, dash, extend, direction and RGBA", () => {
    const ring = new LineInstances();
    const ray = input("ray", [T(10) + 15e6, 1012.75, T(12), 1000]);
    ring.encode([rec(ray), rec(input("hline", [T(5), 7])), rec(input("vline", [T(5), 7]))], 1.5);
    const [f, i] = [ring.data, ring.ints];
    // (int index, int tick, fraction bits, fraction bits) per anchor: the shader's ivec4s.
    expect([i[0], i[1], f[2], f[3], i[4], i[5], f[6], f[7]]).toEqual([
      10, 1012, 0.25, 0.75, 12, 1000, 0, 0,
    ]);
    expect([...f.slice(8, 12)]).toEqual([6, 1, 1, 0]); // 4 CSS px × 1.5; dashed; a ray; p0 → p1
    expect([...f.slice(12, 16)].map((c) => Math.round(c * 255))).toEqual([0x29, 0x62, 0xff, 0x80]);
    // hline / vline: p1 = p0, both ways, the direction given (1 horizontal, 2 vertical).
    expect([i[16], i[17], i[20], i[21], f[26], f[27]]).toEqual([5, 7, 5, 7, 2, 1]);
    expect([i[32], i[33], i[36], i[37], f[42], f[43]]).toEqual([5, 7, 5, 7, 2, 2]);
  });

  it("reports only the instances whose floats changed, and reallocates past its capacity", () => {
    const ring = new LineInstances();
    const many = (n: number, moved = -1) =>
      Array.from({ length: n }, (_, k) =>
        rec(input("segment", [T(k), k === moved ? 9 : 1, T(k + 1), 2])),
      );
    ring.encode(many(10), 1);
    expect([ring.lo, ring.hi]).toEqual([0, 10]);
    ring.encode(many(10), 1);
    expect([ring.lo, ring.hi]).toEqual([0, 0]); // nothing changed: nothing to upload
    ring.encode(many(10, 6), 1);
    expect([ring.lo, ring.hi]).toEqual([6, 7]);
    const before = ring.data;
    ring.encode(many(100), 1);
    expect([ring.data === before, ring.data.length, ring.count]).toEqual([false, 128 * 16, 100]);
  });

  it("the dash LUT is the shader's DASH, entry for entry", () => {
    const glsl = /const vec2 DASH\[3\] = vec2\[3\]\((.*)\);/.exec(DRAWING_LINE.vertex)?.[1] ?? "";
    const entries = [...glsl.matchAll(/vec2\(([\d.]+), ([\d.]+)\)/g)].map((m) => [+m[1]!, +m[2]!]);
    expect(entries).toEqual(DASH_LUT.map((e) => [...e]));
  });
});

/** A 2D context that also records caps and dashes. */
class DashCtx extends FakeCtx2D {
  lineCap = "butt";
  readonly dashes: number[][] = [];
  setLineDash(s: readonly number[]): void {
    this.dashes.push([...s]);
  }
}

const fr = Math.fround;
/** The vertex shader's `project()` in float32 on the real block and ring: device px, y down. */
function standIn(ring: LineInstances, at: number, k: number, b: tf.PaneUniforms): [number, number] {
  const [i, f, u] = [ring.ints, ring.data, b.floats];
  const o = at * LINE_STRIDE + 4 * k; // a_anchor<k>: ints, then intBitsToFloat of the fractions
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

function harness(dpr: number, log: boolean, drawings: DrawingInput[], at: At = {}) {
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
  const ctx2d = new DashCtx();
  const backend = new Canvas2DBackend(ctx2d);
  const builder = new BatchBuilder(graph, backend);
  const block = tf.createPaneUniforms();
  backend.attach(node.id, node.lines);
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
    ctx2d.paths.length = ctx2d.dashes.length = 0;
    backend.submit(builder.drawList, builder.drawCount, vp.plotWidth * dpr, vp.height * dpr);
  };
  frame();
  return { vp, graph, node, ctx2d, block, frame, backend, builder };
}

const nums = (part: string): number[] => part.split(" ").slice(1).map(Number);

describe("Scenario: Thick lines and dashes survive zoom (2D and the GL stand-in agree)", () => {
  it.each([
    [1, false],
    [1.5, false],
    [2, false],
    [1, true],
    [2, true],
  ])("dpr %s, log %s: both put p0 and p1 where the transform does", (dpr, log) => {
    const seg = input("segment", [T(20) + 30e6, 1012.25, T(80), 1047]);
    const { vp, node, ctx2d, block } = harness(dpr, log, [seg]);
    const [path] = ctx2d.paths;
    expect([path?.op, path?.lineWidth, ctx2d.lineCap]).toEqual(["stroke", 4 * dpr, "round"]);
    expect(ctx2d.dashes).toEqual([[12 * dpr, 12 * dpr]]); // a 3-width core + caps, a 6-width period
    const r = node.set.order[0] as Parameters<typeof lineCount>[0];
    for (const k of [0, 1]) {
      const want = [
        tf.indexToScreen(vp, r.idx[k] as number) * dpr,
        tf.priceToScreen(vp, 0, r.tick[k] as number) * dpr,
      ];
      const painted = nums(path?.parts[k] ?? "");
      const shader = standIn(node.lines, 0, k, block);
      for (let c = 0; c < 2; c += 1) {
        expect(Math.abs((painted[c] ?? NaN) - (want[c] as number)), `2D ${k}.${c}`).toBeLessThan(
          0.01,
        );
        expect(Math.abs((shader[c] as number) - (want[c] as number)), `GL ${k}.${c}`).toBeLessThan(
          0.05,
        );
      }
    }
  });

  it("far from the origin (bar ~1e6, ticks ~1e8, a far u_tickBase): both within 0.05 px", () => {
    const T0 = minuteMap().indexToTime(0);
    const far = (i: number): number => T0 + i * 60e6;
    for (const [dpr, log] of [
      [1, false],
      [2, false],
      [1.5, true],
    ] as const) {
      const seg = input("segment", [
        far(1_000_020) + 30e6,
        100_000_012.25,
        far(1_000_080),
        100_000_047,
      ]);
      const at = { map: minuteMap(1_100_000), left: 1_000_000, low: 99_999_990, high: 100_000_060 };
      const { vp, node, ctx2d, block } = harness(dpr, log, [seg], at);
      expect([block.ints[0], block.ints[1]]).toEqual([1_000_000, 99_999_990]); // far bases
      const r = node.set.order[0] as Parameters<typeof lineCount>[0];
      for (const k of [0, 1]) {
        const want = [
          tf.indexToScreen(vp, r.idx[k] as number) * dpr,
          tf.priceToScreen(vp, 0, r.tick[k] as number) * dpr,
        ];
        const painted = nums(ctx2d.paths[0]?.parts[k] ?? "");
        const shader = standIn(node.lines, 0, k, block);
        for (let c = 0; c < 2; c += 1) {
          expect(Math.abs((painted[c] ?? NaN) - (want[c] as number)), `2D ${k}.${c}`).toBeLessThan(
            0.05,
          );
          expect(
            Math.abs((shader[c] as number) - (want[c] as number)),
            `GL ${k}.${c}`,
          ).toBeLessThan(0.05);
        }
      }
    }
  });

  it("past the int32 clamp (2^30 bars) the far anchor stays finite and p0 exact", () => {
    const T0 = 1_790_000_000_000_000;
    const map: tf.IndexTimeMap = {
      length: 2,
      barDurationUs: 1, // 1 µs bars: a time 2^31 µs on is past the 2^30 int clamp
      indexToTime: (i) => (i >= 0 && i < 2 ? T0 + i : Number.NaN),
      timeToIndex: (t) => (t < T0 ? -1 : Math.min(1, Math.floor(t - T0))),
    };
    const ray = input("ray", [T0 + 1, 1_010, T0 + 2 ** 31, 1_040]);
    const { vp, node, ctx2d, block } = harness(1, false, [ray], { map });
    expect(node.lines.ints[4]).toBe(2 ** 30); // clamped, its fraction zeroed
    expect(node.lines.data[6]).toBe(0);
    const shader = [...standIn(node.lines, 0, 0, block), ...standIn(node.lines, 0, 1, block)];
    const painted = [
      ...nums(ctx2d.paths[0]?.parts[0] ?? ""),
      ...nums(ctx2d.paths[0]?.parts[1] ?? ""),
    ];
    expect([...shader, ...painted].every(Number.isFinite)).toBe(true);
    const x0 = tf.indexToScreen(vp, node.set.order[0]?.idx[0] as number);
    expect(Math.abs((shader[0] as number) - x0)).toBeLessThan(0.05);
  });

  it("zoomed 100x in and out: no re-encode, a 4 CSS px stroke, a 24 CSS px dash period", () => {
    for (const dpr of [1, 1.5, 2]) {
      const seg = input("segment", [T(20), 1010, T(60), 1040]);
      const { vp, graph, node, ctx2d, frame } = harness(dpr, false, [seg]);
      const encodes = node.encodes;
      for (const factor of [100, 0.0001, 100]) {
        vp.zoomAt(600, factor);
        graph.markViewport();
        frame();
        expect(ctx2d.paths[0]?.lineWidth).toBe(4 * dpr);
        expect(ctx2d.dashes[0]?.map((v) => v / dpr)).toEqual([12, 12]);
      }
      expect(node.encodes).toBe(encodes);
    }
  });

  it("an extended line starts a whole number of dash periods before p0, as the shader", () => {
    for (const dpr of [1, 1.5, 2]) {
      const line = input("line", [T(20), 1010, T(60), 1040]);
      const { node, ctx2d, block } = harness(dpr, false, [line]);
      const [x0, y0] = standIn(node.lines, 0, 0, block);
      const [sx, sy] = nums(ctx2d.paths[0]?.parts[0] ?? "");
      const periods = Math.hypot((sx as number) - x0, (sy as number) - y0) / (24 * dpr);
      expect(Math.abs(periods - Math.round(periods))).toBeLessThan(1e-3);
    }
  });
});

describe("the 2D backend's caps and dashes", () => {
  it("a plain line stroked after a drawing-line gets butt caps and no dash back", () => {
    const { graph, ctx2d, backend, frame } = harness(1, false, [
      input("segment", [T(20), 1010, T(60), 1040]),
    ]);
    const grid = new NullSeries("p0/grid");
    Object.assign(grid, { program: PROGRAM.line, count: 1 });
    graph.addNode("p0", "foreground", grid);
    backend.attach(grid.id, {
      data: new Float32Array([0, 0, 100, 100, 1, 1, 1, 1, 1]),
      head: 0,
      stride: 9,
    });
    frame();
    expect(ctx2d.paths.map((p) => p.op)).toEqual(["stroke", "stroke"]);
    expect([ctx2d.dashes, ctx2d.lineCap]).toEqual([[[12, 12], []], "butt"]);
  });
});
