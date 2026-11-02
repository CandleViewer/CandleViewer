// E12-S06 2D parity: the Canvas2D backend paints each candle part exactly where the geometry
// twin (the shader's arithmetic) places it, in the palette's colours: the wick, the body by
// direction, an up body's outline then its 42 % tint inset by a hairline. One fill per colour.
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import {
  CANDLE_STRIDE,
  CandleRing,
  CandleSeries,
  candleRect,
  fullOutline,
  GEOM,
} from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { THEME } from "../layers/fixtures.js";
import { FakeCtx2D } from "./fake-ctx2d.js";

function scene(dpr: number) {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
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
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
  const vp = new ChartViewport(store);
  vp.setSize(200, 100, dpr);
  vp.setPanePlot(0, 0, 100);
  vp.setPriceInfo(0, 0, 1);
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = 200 * dpr;
  block.floats[5] = 100 * dpr;
  const c = new CandleSeries(ring);
  expect(c.setTheme(THEME)).toBeNull();
  c.frame(vp.barSpacing, dpr);
  return { store, ring, block, c, vp };
}

describe("Canvas2D candle painter (parity with the geometry twin)", () => {
  it.each([1, 1.5, 2])("dpr %f: every part's rect and colour", (dpr) => {
    const { ring, block, c } = scene(dpr);
    const ctx = new FakeCtx2D();
    const be = new Canvas2DBackend(ctx);
    const ids = ["w", "b"];
    for (const id of ids) be.attach(id, ring);
    be.setPaneUniforms(() => block);
    be.setBatchUniforms((b) => c.blocks[ids.indexOf(b.nodeId)] ?? null);
    const list = ids.map(
      (nodeId, i) =>
        ({
          nodeId,
          program: PROGRAM.candle,
          texture: 0,
          first: 0,
          count: ring.capacity,
          layer: 0,
          seq: i,
          lo: 0,
          hi: 0,
        }) as RetainedBatch,
    );
    be.submit(list, 2, 200 * dpr, 100 * dpr);
    const painted = ctx.paths.flatMap((p) => p.parts.map((r) => `${p.style} ${r}`)).sort();
    const css = (row: number): string => {
      const p = c.palette;
      const b = (i: number): number => Math.round((p[row * 4 + i] ?? 0) * 255);
      return `rgba(${b(0)}, ${b(1)}, ${b(2)}, ${b(3) / 255})`;
    };
    const want: string[] = [];
    const out = new Float64Array(4);
    const hair = c.geom[GEOM.hair] ?? 1;
    for (let i = 0; i < ring.length; i += 1) {
      const at = ((ring.head + i) & (ring.capacity - 1)) * CANDLE_STRIDE;
      const v = (k: number): number => ring.ints[at + k] ?? 0;
      const dir = (v(4) >> 4) & 3;
      for (const part of [0, 1]) {
        const [ib, tb] = [block.ints[0] ?? 0, block.ints[1] ?? 0];
        candleRect(part, i, v(0), v(1), v(2), v(3), dir, block.floats, ib, tb, c.geom, out);
        const [x, y, w, hh] = [out[0] ?? 0, out[1] ?? 0, out[2] ?? 0, out[3] ?? 0];
        const row = part === 0 || dir >= 2 ? 2 : dir; // wick / neutral, else up 0 / down 1
        want.push(`${css(row)} rect ${x} ${y} ${w} ${hh}`);
        if (part === 1 && dir === 0) {
          const [ix, iw] = fullOutline(w, c.geom) ? [x + hair, w - 2 * hair] : [x, w];
          want.push(`${css(3)} rect ${ix} ${y + hair} ${iw} ${hh - 2 * hair}`);
        }
      }
    }
    expect(painted).toEqual(want.sort());
    expect(ctx.count("fill")).toBe(4); // wick/neutral, up, up tint, down: one fill each
  });

  it("skips a candle batch with no batch block, and counts it", () => {
    const { ring, block } = scene(1);
    const be = new Canvas2DBackend(new FakeCtx2D());
    be.attach("w", ring);
    be.setPaneUniforms(() => block);
    const b = {
      nodeId: "w",
      program: PROGRAM.candle,
      texture: 0,
      first: 0,
      count: 8,
      layer: 0,
      seq: 0,
      lo: 0,
      hi: 0,
    };
    be.submit([b as RetainedBatch], 1, 200, 100);
    expect(be.trace.skipped).toBe(1);
  });
});
