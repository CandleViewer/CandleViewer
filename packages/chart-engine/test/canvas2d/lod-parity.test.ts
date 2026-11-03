// E12-S09 2D parity for the L1 mark and the L2 column (E12-D06 §5.3 / §5.4) at DPR 1, 1.5 and
// 2: the Canvas2D backend paints each part where the geometry twin places it, in the palette row
// the shader picks: hairline wicks; a down body solid; an up body outline-only (its top and
// bottom hairlines) from 2 device px, else its `dash.1-1` rows; at L2 every entry's neutral
// column and its span, an up span dashed, O = C a dot.
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import {
  CANDLE_PART,
  CANDLE_STRIDE,
  CandleRing,
  CandleSeries,
  candleRect,
  ColumnEntries,
  columnRect,
  dashOn,
  FILL,
  fillMode,
  GEOM,
  partColor,
} from "../../src/layers/index.js";
import type { VertexSource } from "../../src/scene/gpu-types.js";
import { BarStore } from "../../src/model/index.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { foldOracle, rowsBatch } from "../layers/column-oracle.js";
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

function paint(dpr: number, tier: 1 | 2) {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const c = new CandleSeries(ring);
  ring.sync(store, store.append(rowsBatch(ROWS)));
  const vp = new ChartViewport(store);
  vp.setSize(W, H, dpr);
  vp.setPanePlot(0, 0, H);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, 0, 20);
  const spacing = tier === 1 ? 2 : 0.5;
  vp.setTimeRange(0, (W / spacing - 1) * 60e6);
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = W * dpr;
  block.floats[5] = H * dpr;
  expect(c.setTheme(THEME)).toBeNull();
  const px = vp.barSpacing * dpr;
  const width = Math.ceil(W * dpr);
  const entries = new ColumnEntries(width);
  entries.write(foldOracle(store, vp.leftIndex, px, store.length, width));
  c.frame(vp.barSpacing, dpr, 0, 5, 0, 0, tier, tier === 2 ? entries : null);
  const src: VertexSource = tier === 2 ? entries : ring;
  const ctx = new FakeCtx2D();
  const be = new Canvas2DBackend(ctx);
  const ids = ["w", "b"];
  for (const id of ids) be.attach(id, src);
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
  return { ring, entries, block, c, ctx };
}

describe("Canvas2D L1 / L2 painter (parity with the geometry twin)", () => {
  for (const tier of [1, 2] as const) {
    it.each([1, 1.5, 2])(`L${tier}, dpr %f: every part's rects and colour`, (dpr) => {
      const { ring, entries, block, c, ctx } = paint(dpr, tier);
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
      const n = tier === 2 ? entries.count : ring.length;
      for (let i = 0; i < n; i += 1) {
        const at = tier === 2 ? i * CANDLE_STRIDE : ((ring.head + i) & 7) * CANDLE_STRIDE;
        const v = (k: number): number => (tier === 2 ? entries.ints : ring.ints)[at + k] ?? 0;
        const m = tier === 2 ? v(4) & 3 : v(4) >> 4;
        const parts =
          tier === 2
            ? [CANDLE_PART.columnWick, CANDLE_PART.columnSpan]
            : [CANDLE_PART.wick, CANDLE_PART.body];
        for (const part of parts) {
          if (tier === 2)
            columnRect(part, v(4) >> 4, v(0), v(1), v(2), v(3), block.floats, tb, c.geom, out);
          else candleRect(part, i, v(0), v(1), v(2), v(3), m, block.floats, ib, tb, c.geom, out);
          const [x, y, w, h] = [out[0] ?? 0, out[1] ?? 0, out[2] ?? 0, out[3] ?? 0];
          if (part === CANDLE_PART.wick || part === CANDLE_PART.columnWick) expect(w).toBe(hair);
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
  }
});
