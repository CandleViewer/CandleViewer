// E12-S06 2D parity, OHLC and the gap seam: the Canvas2D backend paints every stem, both ticks of
// every bar and each visible seam exactly where the geometry twin (the shader's arithmetic) puts
// them, in `partColor`'s palette rows, at DPR 1, 1.5 and 2; below 5 CSS px the candle mark.
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import {
  BarSeries,
  CANDLE_PART,
  CANDLE_STRIDE,
  CandleRing,
  candleRect,
  fullOutline,
  GEOM,
  partColor,
} from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { THEME } from "../layers/fixtures.js";
import { FakeCtx2D } from "./fake-ctx2d.js";

function scene(dpr: number, bars: number) {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const c = new BarSeries(ring);
  const open = Int32Array.of(10, 14, 12, 12, 9);
  ring.sync(
    store,
    store.append({
      time: Float64Array.from(open, (_, i) => i * 60e6),
      open,
      high: Int32Array.of(16, 15, 13, 12, 12),
      low: Int32Array.of(8, 9, 11, 12, 7),
      close: Int32Array.of(15, 10, 12, 12, 11), // up, down, doji, zero-range, up
      volume: new Float32Array(5).fill(1),
      flags: Uint8Array.of(0, 0, 1, 0, 1), // gaps before bars 2 and 4
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
  const vp = new ChartViewport(store);
  vp.setSize(200, 100, dpr);
  vp.setPanePlot(0, 0, 100);
  vp.setPriceInfo(0, 0, 1);
  vp.setTimeRange(0, (bars - 1) * 60e6);
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = 200 * dpr;
  block.floats[5] = 100 * dpr;
  expect(c.setTheme(THEME)).toBeNull();
  c.frame(vp.barSpacing, dpr, 0, 4);
  return { ring, block, c, vp };
}

function paint(dpr: number, bars: number) {
  const { ring, block, c } = scene(dpr, bars);
  const ctx = new FakeCtx2D();
  const be = new Canvas2DBackend(ctx);
  const ids = ["stem", "ticks", "seam"];
  ids.forEach((id, i) => be.attach(id, c.sources[i] ?? ring));
  be.setPaneUniforms(() => block);
  be.setBatchUniforms((b) => c.blocks[ids.indexOf(b.nodeId)] ?? null);
  be.trace.enabled = true;
  const list = ids.map(
    (nodeId, i) =>
      ({
        nodeId,
        program: PROGRAM.candle,
        texture: 0,
        first: 0,
        count: i === 2 ? c.seams.capacity : ring.capacity,
        layer: 0,
        seq: i,
        lo: 0,
        hi: 0,
      }) as RetainedBatch,
  );
  be.submit(list, 3, 200 * dpr, 100 * dpr);
  const painted = ctx.paths.flatMap((p) => p.parts.map((r) => `${p.style} ${r}`)).sort();
  const css = (row: number): string => {
    const b = (i: number): number => Math.round((c.palette[row * 4 + i] ?? 0) * 255);
    return `rgba(${b(0)}, ${b(1)}, ${b(2)}, ${b(3) / 255})`;
  };
  const want: string[] = [];
  const out = new Float64Array(4);
  const [ib, tb] = [block.ints[0] ?? 0, block.ints[1] ?? 0];
  const hair = c.geom[GEOM.hair] ?? 1;
  const push = (row: number, x: number, y: number, w: number, h: number): void => {
    if (w > 0 && h > 0) want.push(`${css(row)} rect ${x} ${y} ${w} ${h}`);
  };
  for (let i = 0; i < ring.length; i += 1) {
    const at = ((ring.head + i) & (ring.capacity - 1)) * CANDLE_STRIDE;
    const v = (k: number): number => ring.ints[at + k] ?? 0;
    const dir = (v(4) >> 4) & 3;
    for (let b = 0; b < 2; b += 1) {
      const part = c.blocks[b]?.ints[0] ?? 0;
      for (let sub = 0; sub < (part === CANDLE_PART.ticks ? 2 : 1); sub += 1) {
        candleRect(part, i, v(0), v(1), v(2), v(3), dir, block.floats, ib, tb, c.geom, out, sub);
        const [x, y, w, h] = [out[0] ?? 0, out[1] ?? 0, out[2] ?? 0, out[3] ?? 0];
        push(partColor(part, dir), x, y, w, h);
        if (part === CANDLE_PART.body && dir === 0) {
          const [ix, iw] = fullOutline(w, c.geom) ? [x + hair, w - 2 * hair] : [x, w];
          push(3, ix, y + hair, iw, h - 2 * hair);
        }
      }
    }
  }
  for (const i of [2, 4]) {
    candleRect(CANDLE_PART.seam, i, 0, 0, 0, 0, 0, block.floats, ib, tb, c.geom, out);
    push(partColor(CANDLE_PART.seam, 0), out[0] ?? 0, out[1] ?? 0, out[2] ?? 0, out[3] ?? 0);
  }
  return { painted, want: want.sort(), trace: be.trace, c };
}

describe("Canvas2D OHLC painter (parity with the geometry twin)", () => {
  it.each([1, 1.5, 2])("dpr %f: stems, both ticks and the seams, by colour", (dpr) => {
    const { painted, want, trace, c } = paint(dpr, 5); // ≈ 40 CSS px a bar: ticks drawn
    expect(c.blocks[1]?.ints[0]).toBe(CANDLE_PART.ticks);
    expect(painted).toEqual(want);
    expect(trace.labels).toEqual(["series.ohlc.stem", "series.ohlc.ticks", "series.ohlc.seam"]);
  });

  it.each([1, 1.5, 2])("dpr %f: under 5 CSS px the candle mark, still parity", (dpr) => {
    const { painted, want, c } = paint(dpr, 60); // ≈ 3.4 CSS px a bar
    expect(c.blocks.slice(0, 2).map((b) => b.ints[0])).toEqual([0, 1]);
    expect(painted).toEqual(want);
  });

  it("no seam in view: the seam batch is not painted, not traced", () => {
    const { ring, block, c } = scene(1, 5);
    c.frame(40, 1, 0, 1); // bars 0-1 only: no gap_before among them
    const be = new Canvas2DBackend(new FakeCtx2D());
    be.attach("seam", c.seams);
    be.setPaneUniforms(() => block);
    be.setBatchUniforms(() => c.blocks[2] ?? null);
    be.trace.enabled = true;
    const b = { nodeId: "seam", program: PROGRAM.candle, texture: 0, first: 0, count: 16 };
    be.submit([{ ...b, layer: 0, seq: 0, lo: 0, hi: 0 } as RetainedBatch], 1, 200, 100);
    expect([be.trace.nodes, be.trace.skipped, ring.length]).toEqual([[], 0, 5]);
  });
});
