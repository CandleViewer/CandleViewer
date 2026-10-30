// The Canvas 2D backend (E11-T05): painters through the pane block only, bucketing by style, the
// disclosed skips, and the scenario gates S4 (colour-only cells) and S5 (O(buckets) ops).
import { describe, expect, it } from "vitest";
import { Degraded2dPanBench } from "../../bench/scenes/degraded-2d-pan.js";
import { Canvas2DBackend, MAX_BUCKETS } from "../../src/canvas2d/backend.js";
import { asCtx2D } from "../../src/canvas2d/ctx2d.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import {
  ChartViewport,
  createPaneUniforms,
  indexToScreen,
  priceToScreen,
  writePaneUniforms,
} from "../../src/viewport/index.js";
import { FakeCtx2D } from "./fake-ctx2d.js";

const batch = (nodeId: string, program: number, count: number, layer = 0): RetainedBatch => ({
  nodeId,
  program,
  texture: 0,
  first: 0,
  count,
  layer,
  seq: 0,
  lo: 0,
  hi: 0,
});

/** Bar-cell instances: [index, tick] as int32 bits, then [width bars, height ticks], then RGBA. */
function cells(rows: readonly (readonly number[])[]): Float32Array {
  const data = new Float32Array(rows.length * 8);
  const ints = new Int32Array(data.buffer);
  rows.forEach(([i, t, w, h, ...rgba], r) => {
    ints[r * 8] = i ?? 0;
    ints[r * 8 + 1] = t ?? 0;
    data.set([w ?? 0, h ?? 0, ...rgba], r * 8 + 2);
  });
  return data;
}

function setup(dpr = 2) {
  const ctx = new FakeCtx2D();
  const backend = new Canvas2DBackend(ctx);
  const vp = new ChartViewport();
  vp.setSize(400, 200, dpr);
  vp.setPanePlot(0, 0, 200);
  vp.setPriceRange(0, 100, 200);
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  backend.setPaneUniforms(() => block);
  return { ctx, backend, vp, block };
}

const rect = (part: string | undefined): number[] => (part ?? "").split(" ").slice(1).map(Number);

describe("Canvas2DBackend", () => {
  it("Scenario: Footprint degrades to colour-only rather than disappearing (S4: fill, no text)", () => {
    const { ctx, backend } = setup();
    backend.attach("fp", { data: cells([[3, 150, 1, 1, 0, 1, 0, 1]]), head: 0, stride: 8 });
    backend.submit([batch("fp", PROGRAM.barCell, 1)], 1, 800, 400);
    expect(ctx.count("fill")).toBe(1);
    expect(ctx.count("fillText")).toBe(0);
    expect(ctx.paths.at(-1)?.style).toBe("rgba(0, 255, 0, 1)");
  });

  it("places a cell exactly where the shared transform puts its bar and ticks (device px)", () => {
    const { ctx, backend, vp } = setup(2);
    backend.attach("c", { data: cells([[7, 120, 1, 10, 1, 0, 0, 1]]), head: 0, stride: 8 });
    backend.submit([batch("c", PROGRAM.barCell, 1)], 1, 800, 400);
    const [x, y, w, h] = rect(ctx.paths.at(-1)?.parts[0]);
    const cx = indexToScreen(vp, 7) * 2;
    expect((x ?? 0) + (w ?? 0) / 2).toBeCloseTo(cx, 3);
    expect(w).toBeCloseTo(vp.barSpacing * 2, 3);
    expect((y ?? 0) + (h ?? 0)).toBeCloseTo(priceToScreen(vp, 0, 120) * 2, 3);
    expect(y).toBeCloseTo(priceToScreen(vp, 0, 130) * 2, 3);
  });

  it("strokes lines and fills quads y-up through u_viewport, one path per style", () => {
    const { ctx, backend } = setup(1);
    const line = new Float32Array([0, 0, 400, 200, 2, 0, 0, 1, 1, 0, 100, 400, 100, 2, 0, 0, 1, 1]);
    const quad = new Float32Array([10, 20, 30, 40, 1, 1, 1, 0.5]);
    backend.attach("l", { data: line, head: 0, stride: 9 });
    backend.attach("q", { data: quad, head: 0, stride: 8 });
    backend.setBackground("#123456");
    backend.submit([batch("l", PROGRAM.line, 2), batch("q", PROGRAM.quad, 1)], 2, 400, 200);
    const [bg, stroke, fill] = ctx.paths;
    expect(bg).toMatchObject({ op: "fill", style: "#123456" });
    expect(stroke).toMatchObject({ op: "stroke", style: "rgba(0, 0, 255, 1)", lineWidth: 2 });
    expect(stroke?.parts).toEqual([
      "moveTo 0 200",
      "lineTo 400 0",
      "moveTo 0 100",
      "lineTo 400 100",
    ]);
    expect(fill).toMatchObject({ style: "rgba(255, 255, 255, 0.5019607843137255)" });
    expect(fill?.parts).toEqual(["rect 10 140 30 40"]);
    expect([backend.trace.draws, backend.trace.programSwitches]).toEqual([2, 2]);
  });

  it("draws line and quad in backing-store px when no pane block is bound", () => {
    const ctx = new FakeCtx2D();
    const backend = new Canvas2DBackend(ctx);
    backend.attach("q", { data: new Float32Array([0, 0, 10, 10, 0, 0, 0, 1]), head: 0, stride: 8 });
    backend.attach("c", { data: cells([[0, 0, 1, 1, 0, 0, 0, 1]]), head: 0, stride: 8 });
    backend.submit([batch("q", PROGRAM.quad, 1), batch("c", PROGRAM.barCell, 1)], 2, 100, 50);
    expect(ctx.paths.at(-1)?.parts).toEqual(["rect 0 40 10 10"]);
    expect(backend.trace.skipped).toBe(1); // a cell needs the pane block
    expect(ctx.log).toContain("clearRect"); // no background: cleared only
  });

  it("skips and counts sdf-text and too-narrow rings; an unattached node draws nothing (BQ-88)", () => {
    const { ctx, backend } = setup();
    backend.attach("t", { data: new Float32Array(16), head: 0, stride: 8 });
    backend.attach("n", { data: new Float32Array(8), head: 0, stride: 4 });
    const list = [
      batch("t", PROGRAM.sdfText, 2),
      batch("n", PROGRAM.quad, 2),
      batch("x", PROGRAM.quad, 2),
      batch("t", 9, 1),
    ];
    backend.submit(list, list.length, 800, 400);
    expect(backend.trace.skipped).toBe(3);
    expect([ctx.count("fill"), ctx.count("fillText"), backend.trace.draws]).toEqual([0, 0, 0]);
  });

  it("keeps layer order: one colour in two layers is two fills, in layer order", () => {
    const { ctx, backend } = setup();
    const red = [1, 0, 0, 1];
    backend.attach("a", { data: cells([[1, 120, 1, 1, ...red]]), head: 0, stride: 8 });
    backend.attach("b", { data: cells([[2, 120, 1, 1, 0, 0, 1, 1]]), head: 0, stride: 8 });
    backend.attach("c", { data: cells([[3, 120, 1, 1, ...red]]), head: 0, stride: 8 });
    const list = [
      batch("a", PROGRAM.barCell, 1, 0),
      batch("b", PROGRAM.barCell, 1, 1),
      batch("c", PROGRAM.barCell, 1, 2),
    ];
    backend.trace.enabled = true;
    backend.submit(list, 3, 800, 400);
    expect(ctx.fills).toEqual(["rgba(255, 0, 0, 1)", "rgba(0, 0, 255, 1)", "rgba(255, 0, 0, 1)"]);
    expect(backend.trace.nodes).toEqual(["a", "b", "c"]);
  });

  it("reads a wrapped ring at its physical slots and re-views a reallocated ring", () => {
    const { ctx, backend } = setup();
    const source = {
      data: cells([
        [5, 120, 1, 1, 0, 0, 0, 1],
        [4, 120, 1, 1, 0, 0, 0, 1],
      ]),
      head: 1,
      stride: 8,
    };
    backend.attach("c", source);
    backend.submit([batch("c", PROGRAM.barCell, 2)], 1, 800, 400);
    const xs = ctx.paths.at(-1)?.parts.map((p) => rect(p)[0] ?? 0) ?? [];
    expect(xs[0]).toBeLessThan(xs[1] ?? 0); // logical 0 is slot 1 (bar 4), then slot 0 (bar 5)
    source.data = cells([[9, 120, 1, 1, 0, 0, 0, 1]]);
    source.head = 0;
    backend.submit([batch("c", PROGRAM.barCell, 5)], 1, 800, 400); // count clamps to capacity
    expect(ctx.paths.at(-1)?.parts).toHaveLength(1);
  });

  it("uploads nothing, holds no GPU memory, cannot be lost, and survives a missing context", () => {
    const backend = new Canvas2DBackend(null);
    backend.uploadSubRange();
    expect([backend.takeUploadedBytes(), backend.gpuMemoryMbEstimate]).toEqual([0, 0]);
    expect([backend.loss, backend.failure, backend.drawsIn2d]).toEqual([null, null, true]);
    backend.attach("q", { data: new Float32Array(8), head: 0, stride: 8 });
    expect(backend.submit([batch("q", PROGRAM.quad, 1)], 1, 10, 10)).toBeNull();
    backend.dispose();
    expect(asCtx2D(null)).toBeNull();
    expect(asCtx2D({ fillRect: () => undefined })).toBeNull();
    expect(asCtx2D(new FakeCtx2D())).not.toBeNull();
  });

  it("keeps painting past the warm style table's ceiling", () => {
    const { ctx, backend } = setup();
    const n = MAX_BUCKETS + 2;
    const rows = Array.from({ length: n }, (_, i) => [
      i,
      120,
      1,
      1,
      (i % 256) / 255,
      Math.floor(i / 256) / 255,
      0,
      1,
    ]);
    backend.attach("c", { data: cells(rows), head: 0, stride: 8 });
    backend.submit([batch("c", PROGRAM.barCell, n)], 1, 800, 400);
    expect(ctx.count("fill")).toBe(n);
  });
});

describe("hostile instance data (non-finite or huge) never throws or draws NaN geometry", () => {
  it("paints only finite geometry with a positive line width, and still counts every draw", () => {
    const { ctx, backend } = setup(1);
    const bad = [NaN, Infinity, -Infinity, 1e38];
    const line = new Float32Array(bad.flatMap((v) => [v, 0, 400, v, v, 0, 0, 1, 1]));
    const quad = new Float32Array(bad.flatMap((v) => [v, 20, v, 40, 1, v, 1, 0.5]));
    const rows = bad.map((v) => [0, 120, v, v, v, 0, 0, 1]);
    backend.attach("l", { data: line, head: 0, stride: 9 });
    backend.attach("q", { data: quad, head: 0, stride: 8 });
    backend.attach("c", { data: cells(rows), head: 0, stride: 8 });
    const list = [
      batch("l", PROGRAM.line, bad.length),
      batch("q", PROGRAM.quad, bad.length),
      batch("c", PROGRAM.barCell, bad.length),
    ];
    expect(() => backend.submit(list, list.length, 400, 200)).not.toThrow();
    expect(backend.trace.draws).toBe(ctx.count("fill") + ctx.count("stroke"));
    expect(backend.trace.draws).toBeGreaterThanOrEqual(3);
    for (const path of ctx.paths) {
      expect(
        path.parts.flatMap((p) => p.split(" ").slice(1).map(Number)).every(Number.isFinite),
      ).toBe(true);
    }
    const widths = ctx.paths.filter((p) => p.op === "stroke").map((p) => p.lineWidth);
    expect(widths.length).toBeGreaterThan(0);
    expect(widths.every((w) => Number.isFinite(w) && w > 0)).toBe(true);
  });

  it("keys a hairline below 1/16 px apart from width 0, so its stroke width is set, not inherited", () => {
    const { ctx, backend } = setup(1);
    const line = new Float32Array([0, 0, 10, 10, 3, 0, 0, 1, 1, 0, 0, 10, 10, 0.01, 0, 0, 1, 1]);
    backend.attach("l", { data: line, head: 0, stride: 9 });
    backend.submit([batch("l", PROGRAM.line, 2)], 1, 400, 200);
    expect(ctx.paths.filter((p) => p.op === "stroke").map((p) => p.lineWidth)).toEqual([3, 1 / 16]);
  });
});

describe("Scenario: The degraded mode remains usable (S5 op-count gate, BQ-95)", () => {
  const opsPerFrame = (bars: number): Record<string, number> => {
    const ctx = new FakeCtx2D();
    const bench = new Degraded2dPanBench(ctx, bars);
    bench.step();
    ctx.log.length = 0;
    bench.step();
    const names = ["beginPath", "fill", "stroke", "fillRect", "clearRect", "fillText"];
    return Object.fromEntries(names.map((n) => [n, ctx.count(n)]));
  };

  it("one path and one fill or stroke per style bucket, the same at 2 000 and 20 000 bars", () => {
    const ops = { beginPath: 3, fill: 2, stroke: 1, fillRect: 1, clearRect: 1, fillText: 0 };
    expect(opsPerFrame(2_000)).toEqual(ops);
    expect(opsPerFrame(20_000)).toEqual(ops);
  });

  it("a pan uploads nothing: the rings are read at draw time", () => {
    const bench = new Degraded2dPanBench(new FakeCtx2D(), 2_000);
    for (let i = 0; i < 5; i += 1) bench.step(-3);
    expect(bench.backend.takeUploadedBytes()).toBe(0);
    expect(bench.backend.trace.draws).toBe(3);
  });

  it.todo("golden images of candles, axes, grid, crosshair and lines per theme (E11-T08, C-14)");
});
