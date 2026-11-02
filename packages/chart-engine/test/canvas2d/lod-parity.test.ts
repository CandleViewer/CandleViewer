// E12-S09 2D parity for the L1 mark (E12-D06 §5.3) at DPR 1, 1.5 and 2: the Canvas2D backend
// paints each part where the geometry twin places it, in the palette row the shader picks:
// hairline wicks; a down body solid; an up body outline-only (its top and bottom hairlines) from
// 2 device px, else its `dash.1-1` rows.
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import {
  CANDLE_PART,
  CANDLE_STRIDE,
  CandleRing,
  CandleSeries,
  candleRect,
  dashOn,
  FILL,
  fillMode,
  GEOM,
  partColor,
} from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { THEME } from "../layers/fixtures.js";
import { FakeCtx2D } from "./fake-ctx2d.js";

const ROWS = [
  [10, 16, 8, 14], // up
  [16, 18, 9, 12], // down
  [12, 14, 10, 12], // doji
  [9, 15, 9, 13], // up
  [13, 13, 4, 5], // down
  [6, 12, 5, 11], // up
];
const W = 40;
const H = 60;

function paint(dpr: number) {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const c = new CandleSeries(ring);
  const col = (k: number): Int32Array => Int32Array.from(ROWS, (r) => r[k] ?? 0);
  ring.sync(
    store,
    store.append({
      time: Float64Array.from(ROWS, (_, i) => i * 60e6),
      open: col(0),
      high: col(1),
      low: col(2),
      close: col(3),
      volume: new Float32Array(ROWS.length).fill(1),
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
  const vp = new ChartViewport(store);
  vp.setSize(W, H, dpr);
  vp.setPanePlot(0, 0, H);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, 0, 20);
  const spacing = 2;
  vp.setTimeRange(0, (W / spacing - 1) * 60e6);
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = W * dpr;
  block.floats[5] = H * dpr;
  expect(c.setTheme(THEME)).toBeNull();
  c.frame(vp.barSpacing, dpr, 0, 5, 0, 0, 1);
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
        count: 64,
        layer: 0,
        seq: i,
      }) as RetainedBatch,
  );
  be.submit(list, 2, W * dpr, H * dpr);
  return { ring, block, c, ctx };
}

describe("Canvas2D L1 painter (parity with the geometry twin)", () => {
  it.each([1, 1.5, 2])("L1, dpr %f: every part's rects and colour", (dpr) => {
    const { ring, block, c, ctx } = paint(dpr);
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
    const modes = new Set<number>();
    const n = ring.length;
    for (let i = 0; i < n; i += 1) {
      const at = ((ring.head + i) & 7) * CANDLE_STRIDE;
      const v = (k: number): number => ring.ints[at + k] ?? 0;
      const m = v(4) >> 4;
      for (const part of [CANDLE_PART.wick, CANDLE_PART.body]) {
        candleRect(part, i, v(0), v(1), v(2), v(3), m, block.floats, ib, tb, c.geom, out);
        const [x, y, w, h] = [out[0] ?? 0, out[1] ?? 0, out[2] ?? 0, out[3] ?? 0];
        if (part === CANDLE_PART.wick) expect(w).toBe(hair);
        const style = css(partColor(part, m));
        const mode = fillMode(part, m, w, c.geom);
        modes.add(mode);
        if (mode === FILL.dash) {
          for (let row = Math.ceil(y - 0.5); row < Math.ceil(y + h - 0.5); row += 1) {
            if (dashOn(row, H * dpr)) want.push(`${style} rect ${x} ${row} ${w} 1`);
          }
        } else if (mode >= FILL.hollow) {
          want.push(`${style} rect ${x} ${y} ${w} ${hair}`);
          want.push(`${style} rect ${x} ${y + h - hair} ${w} ${hair}`);
        } else want.push(`${style} rect ${x} ${y} ${w} ${h}`);
      }
    }
    expect(modes.has(FILL.dash) || modes.has(1 + FILL.hollow)).toBe(true);
    expect([n > 0, painted.length >= 2 * n]).toEqual([true, true]);
    expect(painted).toEqual(want.sort());
  });
});
