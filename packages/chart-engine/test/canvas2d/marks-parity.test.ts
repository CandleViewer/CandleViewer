// E12-S10 2D parity for the marks (E12-D06 §7.1 / §7.3): the Canvas2D backend paints the forming
// ring as exactly the pixels the shader's fragment test (`ringOn`) inks inside the twin's
// `markRect`, and the corrected square as that rect, both in the wick colour, at DPR 1 / 1.5 / 2.
// At L1 the marks batch has no instance, so nothing is painted.
import { describe, expect, it } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import {
  CANDLE_DIR,
  CandleRing,
  CandleSeries,
  candleDir,
  GEOM,
  MARK_HEAVY,
  markRect,
  PALETTE,
  ringOn,
} from "../../src/layers/index.js";
import { BAR_FLAG, BarStore } from "../../src/model/index.js";
import type { RetainedBatch } from "../../src/scene/batch-builder.js";
import { PROGRAM } from "../../src/scene/instance-layout.js";
import { ChartViewport, createPaneUniforms, writePaneUniforms } from "../../src/viewport/index.js";
import { THEME } from "../layers/fixtures.js";
import { FakeCtx2D } from "./fake-ctx2d.js";

const { forming: FORMING, amended: AMENDED } = BAR_FLAG;
const OPEN = [10, 14, 12];
const HIGH = [16, 15, 18];
const LOW = [8, 9, 7];
const CLOSE = [15, 10, 12]; // up, down (amended), doji (forming and amended)

/** `frameCss` overrides the spacing the frame sees (the tier test); else the viewport's. */
function paint(dpr: number, frameCss?: number) {
  const spacing = 20;
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  const c = new CandleSeries(ring);
  expect(c.setTheme(THEME)).toBeNull();
  ring.sync(
    store,
    store.append({
      time: Float64Array.from(OPEN, (_, i) => i * 60e6),
      open: Int32Array.from(OPEN),
      high: Int32Array.from(HIGH),
      low: Int32Array.from(LOW),
      close: Int32Array.from(CLOSE),
      volume: new Float32Array(3).fill(1),
      flags: Uint8Array.of(0, AMENDED, FORMING | AMENDED),
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
  const W = 3 * spacing;
  const vp = new ChartViewport(store);
  vp.setSize(W, 100, dpr);
  vp.setPanePlot(0, 0, 100);
  vp.setPriceInfo(0, 0, 1);
  vp.setPriceRange(0, 0, 25);
  vp.setTimeRange(0, 120e6);
  const block = createPaneUniforms();
  writePaneUniforms(vp, 0, block);
  block.floats[4] = W * dpr;
  block.floats[5] = 100 * dpr;
  c.frame(frameCss ?? vp.barSpacing, dpr, 0, 2);
  const ctx = new FakeCtx2D();
  const be = new Canvas2DBackend(ctx);
  be.attach("marks", c.marks);
  be.setPaneUniforms(() => block);
  be.setBatchUniforms(() => c.blocks[3] ?? null);
  const batch = { nodeId: "marks", program: PROGRAM.candle, texture: 0, first: 0 };
  const list = [{ ...batch, count: c.marks.capacity, layer: 0, seq: 0, lo: 0, hi: 0 }];
  be.submit(list as RetainedBatch[], 1, W * dpr, 100 * dpr);
  return { c, ctx, block, store };
}

/** Every painted pixel, as `x,y`, from the paths' rects (device px). */
const pixels = (ctx: FakeCtx2D): Set<string> => {
  const out = new Set<string>();
  for (const p of ctx.paths) {
    for (const r of p.parts) {
      const [x, y, w, h] = r.split(" ").slice(1).map(Number) as [number, number, number, number];
      for (let py = Math.round(y); py < Math.round(y + h); py += 1) {
        for (let px = Math.round(x); px < Math.round(x + w); px += 1) out.add(`${px},${py}`);
      }
    }
  }
  return out;
};

describe("Canvas2D marks painter (parity with the twin and the fragment test)", () => {
  it.each([1, 1.5, 2])(
    "dpr %f: the ring's inked pixels and the squares, in the wick colour",
    (dpr) => {
      const { c, ctx, block } = paint(dpr);
      const want = new Set<string>();
      const r = new Float64Array(4);
      const hair = c.geom[GEOM.hair] as number;
      for (const [i, kind] of [
        [1, AMENDED],
        [2, FORMING],
        [2, AMENDED],
      ] as const) {
        const [o, h, l, cl] = [OPEN[i], HIGH[i], LOW[i], CLOSE[i]] as [
          number,
          number,
          number,
          number,
        ];
        const d = candleDir(o, h, l, cl);
        const meta = (d << 4) | (d === CANDLE_DIR.down ? MARK_HEAVY : 0); // the entry's word 4
        markRect(kind, i, h, l, o, meta, block.floats, 0, 0, c.geom, r);
        const [x, y, w, hh] = [...r] as [number, number, number, number];
        for (let py = 0; py < hh; py += 1) {
          for (let px = 0; px < w; px += 1) {
            if (kind === AMENDED || ringOn(px, py, w, hh, hair)) want.add(`${x + px},${y + py}`);
          }
        }
      }
      expect(c.blocks[3]?.instances).toBe(3);
      expect([...pixels(ctx)].sort()).toEqual([...want].sort());
      const p = c.palette;
      const b = (k: number): number => Math.round((p[PALETTE.wick * 4 + k] ?? 0) * 255);
      expect(new Set(ctx.fills)).toEqual(
        new Set([`rgba(${b(0)}, ${b(1)}, ${b(2)}, ${b(3) / 255})`]),
      );
    },
  );

  it("at L1 (s < 3 CSS px) nothing is painted: the words carry the state", () => {
    const { ctx, c } = paint(1, 2.99);
    expect(c.blocks[3]?.instances).toBe(0);
    expect(ctx.paths).toHaveLength(0);
  });
});
