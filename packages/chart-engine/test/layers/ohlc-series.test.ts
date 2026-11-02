// E12-S06 OHLC bars and the gap seam in the geometry twin (E12-D06 §3.2, §4.1, §9; BQ-8, BQ-15),
// `BarSeries.frame`'s per-frame part switch below 5 CSS px, and hit-testing as the inverse of the
// drawn geometry (seeded property, README BQ-30: mulberry32, no fast-check).
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  BarSeries,
  CANDLE_DIR,
  CANDLE_PART,
  CANDLE_STRIDE,
  CandleRing,
  CandleSeries,
  candleGeometry,
  candleRect,
  createBarHit,
  GEOM,
  OHLC_TICKS_FROM,
  PALETTE,
  partColor,
  SERIES_PARTS,
} from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import {
  ChartViewport,
  createPaneUniforms,
  screenToIndex,
  writePaneUniforms,
} from "../../src/viewport/index.js";
import { THEME } from "./fixtures.js";

const geom = (s: number, dpr: number): Float32Array => {
  const g = new Float32Array(8);
  candleGeometry(s, dpr, g);
  return g;
};
/** A pane block: 10 device px per bar, 2 px per tick, y = 500 - 2 t (linear), 600 px tall. */
const K = Float64Array.of(10, -2, 500, 0, 0, 600, 0, 0);
const rect = (part: number, ohlc: number[], dir: number, g: Float32Array, sub = 0): number[] => {
  const out = new Float64Array(4);
  const [o, h, l, c] = ohlc as [number, number, number, number];
  candleRect(part, 3, o, h, l, c, dir, K, 0, 0, g, out, sub);
  return [...out];
};
const { stem: STEM, ticks: TICKS, seam: SEAM } = CANDLE_PART;

describe("OHLC geometry (D06 §3.2)", () => {
  // tick = clamp(floor(body / 2), 1, floor((s − 3) / 2)) CSS px, then × dpr.
  it.each([
    [5, 1, 1],
    [6, 1, 1],
    [8, 1, 2],
    [12, 1, 4],
    [48, 1, 17],
    [200, 1, 17],
    [12, 2, 8],
    [12, 1.5, 6],
  ])("spacing %f at dpr %f: tick %i device px", (s, dpr, tick) => {
    expect(geom(s, dpr)[GEOM.tick]).toBe(tick);
  });

  it("property: stem plus ticks stay within s − 1 px (integer DPRs, 3 000 cases)", () => {
    const rng = mulberry32(20261103);
    for (let c = 0; c < 3_000; c += 1) {
      const s = OHLC_TICKS_FROM + rng() * 200;
      const dpr = [1, 2, 3][Math.floor(rng() * 3)] as number;
      const g = geom(s, dpr);
      const span = 2 * (g[GEOM.tick] as number) + 2 * (g[GEOM.hair] as number); // a down stem
      expect(span, `s=${s} dpr=${dpr}`).toBeLessThanOrEqual((s - 1) * dpr);
    }
  });

  const g = geom(12, 1); // body 9, hairline 1, tick 4: the stem on column 35
  it("an up bar: a 1 px stem high → low, the open tick left and the close tick right", () => {
    expect(rect(STEM, [2, 9, 1, 5], CANDLE_DIR.up, g)).toEqual([35, 482, 1, 16]);
    expect(rect(TICKS, [2, 9, 1, 5], CANDLE_DIR.up, g, 0)).toEqual([31, 496, 4, 1]);
    expect(rect(TICKS, [2, 9, 1, 5], CANDLE_DIR.up, g, 1)).toEqual([36, 490, 4, 1]);
  });

  it("a down bar: stem and ticks 2 px, the close tick right of the 2 px stem", () => {
    expect(rect(STEM, [5, 9, 1, 2], CANDLE_DIR.down, g)).toEqual([35, 482, 2, 16]);
    expect(rect(TICKS, [5, 9, 1, 2], CANDLE_DIR.down, g, 0)).toEqual([31, 489, 4, 2]);
    expect(rect(TICKS, [5, 9, 1, 2], CANDLE_DIR.down, g, 1)).toEqual([37, 495, 4, 2]);
  });

  it("D06 §9: a doji is a neutral hairline stem and ticks; zero-range is the neutral mark", () => {
    expect(rect(STEM, [4, 9, 1, 4], CANDLE_DIR.doji, g)).toEqual([35, 482, 1, 16]);
    expect(rect(TICKS, [4, 9, 1, 4], CANDLE_DIR.doji, g, 1)).toEqual([36, 492, 4, 1]);
    expect(rect(STEM, [4, 4, 4, 4], CANDLE_DIR.zeroRange, g)).toEqual([31, 491, 9, 2]);
    expect(rect(TICKS, [4, 4, 4, 4], CANDLE_DIR.zeroRange, g, 0)[2]).toBe(0); // no ticks
    expect([CANDLE_DIR.doji, CANDLE_DIR.zeroRange].map((d) => partColor(STEM, d))).toEqual([
      PALETTE.wick,
      PALETTE.wick,
    ]);
  });

  it("D06 §9: a zero-range candle body is 2 hairlines tall at every spacing (doji: 1 below 8)", () => {
    expect(rect(CANDLE_PART.body, [4, 4, 4, 4], CANDLE_DIR.zeroRange, geom(6, 1))[3]).toBe(2);
    expect(rect(CANDLE_PART.body, [4, 9, 1, 4], CANDLE_DIR.doji, geom(6, 1))[3]).toBe(1);
  });

  it("colours: the wick and the seam neutral; bodies, stems and ticks by direction", () => {
    const table = [0, 1, 2, 3, 4].map((p) => [0, 1, 2, 3].map((d) => partColor(p, d)));
    const [U, D, N] = [PALETTE.up, PALETTE.down, PALETTE.wick];
    expect(table).toEqual([
      [N, N, N, N],
      [U, D, N, N],
      [U, D, N, N],
      [U, D, N, N],
      [N, N, N, N],
    ]);
  });

  it("BQ-8: the seam is a hairline at the slot's left edge over the whole pane", () => {
    expect(rect(SEAM, [0, 0, 0, 0], 0, g)).toEqual([30, 0, 1, 600]);
    expect(rect(SEAM, [0, 0, 0, 0], 0, geom(12, 2))).toEqual([29, 0, 2, 600]);
  });

  it("BQ-8: with a plot rect the seam stays inside it, off the time-axis strip", () => {
    const { c } = series("candles", Uint8Array.of(0, 0, 0, 1, 0, 0));
    c.frame(12, 2, 0, 5, 20, 280); // plot top 20, bottom 280 CSS px at dpr 2
    const out = new Float64Array(4);
    candleRect(SEAM, 3, 0, 0, 0, 0, 0, K, 0, 0, c.geom, out);
    expect([out[1], (out[1] ?? 0) + (out[3] ?? 0)]).toEqual([40, 560]);
    expect((out[1] ?? 0) + (out[3] ?? 0)).toBeLessThan(K[5] ?? 0); // the canvas is taller
  });
});

function series(shape: "candles" | "bars", flags?: Uint8Array) {
  const store = new BarStore({ initialCapacity: 16 });
  const ring = new CandleRing();
  const c = shape === "bars" ? new BarSeries(ring) : new CandleSeries(ring);
  const open = Int32Array.of(10, 14, 12, 12, 9, 11);
  ring.sync(
    store,
    store.append({
      time: Float64Array.from(open, (_, i) => i * 60e6),
      open,
      high: Int32Array.of(16, 15, 13, 12, 12, 13),
      low: Int32Array.of(8, 9, 11, 12, 7, 10),
      close: Int32Array.of(15, 10, 12, 12, 11, 10),
      volume: new Float32Array(6).fill(1),
      ...(flags && { flags }),
      priceOrigin: 0,
      tickSize: 1,
    }),
  );
  expect(c.setTheme(THEME)).toBeNull();
  return { store, ring, c };
}

describe("BarSeries / CandleSeries per frame", () => {
  it("names its parts for the draw trace", () => {
    expect(series("candles").c.blocks.map((b) => b.label)).toEqual([
      "series.candle.wick",
      "series.candle.body",
      "series.candle.seam",
    ]);
    expect(series("bars").c.blocks.map((b) => b.label)).toEqual([
      "series.ohlc.stem",
      "series.ohlc.ticks",
      "series.ohlc.seam",
    ]);
    expect(SERIES_PARTS.bars.map(([, p]) => p)).toEqual([STEM, TICKS, SEAM]);
  });

  it("OHLC from 5 CSS px: stem (4 vertices) and ticks (10); below it the candle mark", () => {
    const { c } = series("bars");
    const parts = (): number[][] => c.blocks.slice(0, 2).map((b) => [b.ints[0] ?? -1, b.vertices]);
    c.frame(5, 1);
    expect(parts()).toEqual([
      [STEM, 4],
      [TICKS, 10],
    ]);
    c.frame(4.99, 1);
    expect(parts()).toEqual([
      [CANDLE_PART.wick, 4],
      [CANDLE_PART.body, 4],
    ]);
    const candles = series("candles").c;
    candles.frame(200, 1);
    expect(candles.blocks.slice(0, 2).map((b) => b.ints[0])).toEqual([0, 1]);
  });

  it("BQ-8 / BQ-12: the seam draws only with a gap_before bar in view and time-aligned", () => {
    const { c, ring } = series("candles", Uint8Array.of(0, 0, 0, 1, 0, 0));
    const seam = c.blocks[2];
    c.frame(10, 1, 0, 5);
    expect([seam?.instances, seam?.ints.slice(1)]).toEqual([
      1,
      Int32Array.of(ring.head, ring.capacity - 1, 6),
    ]);
    c.frame(10, 1, 4, 5);
    expect(seam?.instances).toBe(0);
    c.timeAligned = false;
    c.frame(10, 1, 0, 5);
    expect(seam?.instances).toBe(0);
    const none = series("candles").c;
    none.frame(10, 1, 0, 5);
    expect(none.blocks[2]?.instances).toBe(0);
  });
});

describe("property: hit-testing is the inverse of the drawn geometry", () => {
  it.each(["candles", "bars"] as const)("%s: 600 seeded cases", (shape) => {
    const rng = mulberry32(shape === "bars" ? 20261104 : 20261105);
    const failures: string[] = [];
    const out = new Float64Array(4);
    const hit = createBarHit();
    const seen = { pixels: 0, hits: 0, misses: 0, small: 0 };
    for (let n = 0; n < 600 && failures.length < 3; n += 1) {
      const dpr = [1, 1.5, 2, 3][Math.floor(rng() * 4)] as number;
      const { store, ring, c } = series(shape);
      const vp = new ChartViewport(store);
      vp.setSize(120, 100, dpr);
      vp.setPanePlot(0, 0, 100);
      vp.setPriceInfo(0, 0, 1);
      vp.setPriceRange(0, 6 - rng() * 2, 17 + rng() * 2); // the bars span the plot
      // Spacing ≈ 17-20 CSS px, or ≈ 4-5 px (OHLC's candle mark below 5).
      const span = rng() < 0.5 ? 5 : 24;
      vp.setTimeRange(-rng() * 60e6, (span + rng()) * 60e6);
      const block = createPaneUniforms();
      writePaneUniforms(vp, 0, block);
      c.frame(vp.barSpacing, dpr);
      const [k, i0, t0] = [block.floats, block.ints[0] ?? 0, block.ints[1] ?? 0];
      const tol = [0, 4, 10][Math.floor(rng() * 3)] as number;
      // (1) a point inside any drawn part hits that bar at distance 0
      for (let j = 0; j < ring.length; j += 1) {
        const at = ((ring.head + j) & (ring.capacity - 1)) * CANDLE_STRIDE;
        const v = (q: number): number => ring.ints[at + q] ?? 0;
        for (let b = 0; b < 2; b += 1) {
          const part = c.blocks[b]?.ints[0] ?? 0;
          for (let sub = 0; sub < (part === TICKS ? 2 : 1); sub += 1) {
            candleRect(
              part,
              j,
              v(0),
              v(1),
              v(2),
              v(3),
              (v(4) >> 4) & 3,
              k,
              i0,
              t0,
              c.geom,
              out,
              sub,
            );
            const [x, y, w, h] = [...out] as [number, number, number, number];
            if (w <= 0) continue;
            const px = x + rng() * w; // any point of the drawn rect
            const py = y + rng() * h;
            const [cx, cy] = [px / dpr, py / dpr];
            const index = screenToIndex(vp, cx);
            if (index !== j) continue; // a mark reaching a neighbour's slot answers there
            const ok = c.hitTest(cx, cy, index, k, i0, t0, tol, hit);
            seen.pixels += 1;
            if (!ok || hit.index !== j || hit.distancePx !== 0) {
              failures.push(`case ${n}: pixel (${px}, ${py}) of bar ${j} part ${part} missed`);
            }
          }
        }
      }
      // (2) a random point hits iff some drawn part of its slot's bar is within tolerance
      const cx = rng() * 120;
      const cy = rng() * 100;
      const index = screenToIndex(vp, cx);
      let d = Infinity;
      if (index >= 0 && index < ring.length) {
        const at = ((ring.head + index) & (ring.capacity - 1)) * CANDLE_STRIDE;
        const v = (q: number): number => ring.ints[at + q] ?? 0;
        for (let b = 0; b < 2; b += 1) {
          const part = c.blocks[b]?.ints[0] ?? 0;
          for (let sub = 0; sub < (part === TICKS ? 2 : 1); sub += 1) {
            const dir = (v(4) >> 4) & 3;
            candleRect(part, index, v(0), v(1), v(2), v(3), dir, k, i0, t0, c.geom, out, sub);
            const [x, y, w, h] = [...out] as [number, number, number, number];
            if (w <= 0) continue;
            const dx = Math.max(x - cx * dpr, 0, cx * dpr - (x + w));
            const dy = Math.max(y - cy * dpr, 0, cy * dpr - (y + h));
            d = Math.min(d, Math.hypot(dx, dy) / dpr);
          }
        }
      }
      const ok = c.hitTest(cx, cy, index, k, i0, t0, tol, hit);
      seen[ok ? "hits" : "misses"] += 1;
      seen.small += vp.barSpacing < 5 ? 1 : 0;
      if (ok !== d <= tol || (ok && Math.abs(hit.distancePx - d) > 1e-9)) {
        failures.push(`case ${n}: (${cx}, ${cy}) bar ${index}: hit ${ok}, nearest ${d}`);
      }
    }
    expect(failures).toEqual([]);
    for (const [key, v] of Object.entries(seen)) expect(v, key).toBeGreaterThan(20);
  });

  it("misses outside the series, while the theme hides it, and on an empty ring", () => {
    const { c } = series("candles");
    const hit = createBarHit();
    expect(c.hitTest(0, 0, -1, K, 0, 0, 10, hit)).toBe(false);
    expect(c.hitTest(0, 0, 6, K, 0, 0, 10, hit)).toBe(false);
    c.setTheme({});
    expect(c.hitTest(35, 490, 3, K, 0, 0, 1e9, hit)).toBe(false);
    const empty = new CandleSeries(new CandleRing());
    empty.setTheme(THEME);
    expect(empty.hitTest(0, 0, 0, K, 0, 0, 10, hit)).toBe(false);
    expect(hit).toEqual({ index: -1, part: -1, distancePx: Infinity });
  });
});
