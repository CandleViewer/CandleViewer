// E12-S07 2D parity for hollow candles (E12-D06 §4.2) at dpr 1, 1.5 and 2: the Canvas2D backend
// paints each part where the geometry twin places it, in the palette row the shader picks: the
// neutral wick, a solid body whole, a hollow body as its outline alone (the shader's discard: top
// and bottom hairlines, the sides too from 3 CSS px wide). Over Heikin-Ashi too: the same parts
// over the ring's HA bars.
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import {
  CANDLE_PART,
  CANDLE_STRIDE,
  CandleRing,
  CandleSeries,
  candleRect,
  fullOutline,
  GEOM,
  hollowFill,
  PALETTE,
  partColor,
} from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { THEME } from "../layers/fixtures.js";
import { FakeCtx2D } from "./fake-ctx2d.js";

function paint(dpr: number, ha: boolean) {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const c = new CandleSeries(ring, "hollow");
  const open = Int32Array.of(10, 16, 8, 15, 9, 12, 12, 11);
  ring.sync(
    store,
    store.append({
      time: Float64Array.from(open, (_, i) => i * 60e6),
      open,
      high: Int32Array.of(16, 18, 13, 16, 14, 12, 14, 13),
      low: Int32Array.of(8, 9, 7, 9, 8, 12, 10, 9),
      // the four marks, a zero-range bar, then E12-D06 §9's doji row: an up doji (12 >= 12, wick 1
      // hairline) and a down doji (11 < 12, wick 2 hairlines)
      close: Int32Array.of(14, 12, 10, 11, 13, 12, 12, 11),
      volume: new Float32Array(8).fill(1),
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
  if (ha) c.setKind("hollow", true, store);
  const vp = new ChartViewport(store);
  vp.setSize(200, 100, dpr);
  vp.setPanePlot(0, 0, 100);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, 0, 20);
  vp.setTimeRange(-30e6, 450e6); // ≈ 25 CSS px a bar: the hollow parts, full outlines
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = 200 * dpr;
  block.floats[5] = 100 * dpr;
  expect(c.setTheme(THEME)).toBeNull();
  c.frame(vp.barSpacing, dpr);
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
  return { ring, block, c, ctx };
}

describe("Canvas2D hollow painter (parity with the geometry twin)", () => {
  for (const ha of [false, true]) {
    it.each([1, 1.5, 2])(
      `dpr %f${ha ? ", Heikin-Ashi" : ""}: every part's rects and colour`,
      (dpr) => {
        const { ring, block, c, ctx } = paint(dpr, ha);
        expect(c.blocks.map((b) => b.ints[0])).toEqual([5, 6, 4, 7]);
        const painted = ctx.paths.flatMap((p) => p.parts.map((r) => `${p.style} ${r}`)).sort();
        const css = (row: number): string => {
          const p = c.palette;
          const b = (i: number): number => Math.round((p[row * 4 + i] ?? 0) * 255);
          return `rgba(${b(0)}, ${b(1)}, ${b(2)}, ${b(3) / 255})`;
        };
        const want: string[] = [];
        const out = new Float64Array(4);
        const hair = c.geom[GEOM.hair] ?? 1;
        const [ib, tb] = [block.ints[0] ?? 0, block.ints[1] ?? 0];
        let hollow = 0;
        for (let i = 0; i < ring.length; i += 1) {
          const at = ((ring.head + i) & (ring.capacity - 1)) * CANDLE_STRIDE;
          const v = (k: number): number => ring.ints[at + k] ?? 0;
          const m = v(4) >> 4;
          for (const part of [CANDLE_PART.hollowWick, CANDLE_PART.hollowBody]) {
            candleRect(part, i, v(0), v(1), v(2), v(3), m, block.floats, ib, tb, c.geom, out);
            const [x, y, w, h] = [out[0] ?? 0, out[1] ?? 0, out[2] ?? 0, out[3] ?? 0];
            const style = css(partColor(part, m));
            if (!hollowFill(part, m)) {
              want.push(`${style} rect ${x} ${y} ${w} ${h}`);
              continue;
            }
            hollow += 1;
            want.push(`${style} rect ${x} ${y} ${w} ${hair}`);
            want.push(`${style} rect ${x} ${y + h - hair} ${w} ${hair}`);
            expect(fullOutline(w, c.geom)).toBe(true);
            want.push(`${style} rect ${x} ${y + hair} ${hair} ${h - 2 * hair}`);
            want.push(`${style} rect ${x + w - hair} ${y + hair} ${hair} ${h - 2 * hair}`);
          }
        }
        expect(hollow).toBeGreaterThan(0);
        // E12-D06 §9's doji row, pinned: the up doji's wick is 1 hairline, the down doji's 2, the
        // colour the previous-close row (up / down), the body painted whole.
        const dojiOf = (i: number): [number, number] => {
          const at = ((ring.head + i) & (ring.capacity - 1)) * CANDLE_STRIDE;
          const v = (k: number): number => ring.ints[at + k] ?? 0;
          candleRect(
            CANDLE_PART.hollowWick,
            i,
            v(0),
            v(1),
            v(2),
            v(3),
            v(4) >> 4,
            block.floats,
            ib,
            tb,
            c.geom,
            out,
          );
          return [out[2] ?? 0, partColor(CANDLE_PART.hollowBody, v(4) >> 4)];
        };
        expect([dojiOf(6), dojiOf(7)]).toEqual([
          [hair, PALETTE.up],
          [2 * hair, PALETTE.down],
        ]);
        expect(painted).toEqual(want.sort());
      },
    );
  }
});
