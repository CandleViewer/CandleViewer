// E12-S11 PR A1: `SeriesPriceSource`, a series' `BarStore` and `CandleRing` as autoscale's
// `PriceExtentSource` (26 §3.5, :390). Seeded mulberry32 loops (README BQ-30, no fast-check):
// (1) the extent and minLow are the brute-force min / max of the DRAWN instance words (the ring:
// real bars, or Heikin-Ashi while it is on), over the visible slice; (2) a series that is not the
// viewport's time map is read through time, and in the pane's price frame (its own origin and
// tick converted, rounded outward), its `minLow` and `close` likewise; (3) `close` is the store's
// real close (R-4); (4) in closes-only mode (line, area, baseline) the extent and minLow read the
// close word alone; (5) a secondary series off the visible part of the map reads by time.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { CandleRing, HaRing, SeriesPriceSource } from "../../src/layers/index.js";
import { BarStore, type BarBatch } from "../../src/model/index.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { bars, STEP, T0 } from "../model/fixtures.js";
import { ringBar } from "./fixtures.js";

const CASES = 500;

function randomBars(rng: () => number, first: number, count: number, step = STEP): BarBatch {
  const b = bars(first, count);
  const time = Float64Array.from({ length: count }, (_, i) => T0 + (first + i) * step);
  for (let j = 0; j < count; j += 1) {
    const lo = Math.floor(rng() * 400) - 200;
    const hi = lo + Math.floor(rng() * 40);
    b.low[j] = lo;
    b.high[j] = hi;
    b.open[j] = lo + Math.floor(rng() * (hi - lo + 1));
    b.close[j] = lo + Math.floor(rng() * (hi - lo + 1));
  }
  return { ...b, time };
}

function seriesOf(b: BarBatch, ha: boolean): { store: BarStore; ring: CandleRing } {
  const store = new BarStore({ initialCapacity: 8 });
  const ring = new CandleRing();
  ring.sync(store, store.replace(b));
  if (ha) ring.setMode(store, false, new HaRing());
  return { store, ring };
}

/** min low / max high (or min / max close) of the drawn words over bars [a, b). */
function drawn(ring: CandleRing, a: number, b: number, closes = false): [number, number] | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = Math.max(0, a); i < Math.min(ring.length, b); i += 1) {
    const w = ringBar(ring, i);
    lo = Math.min(lo, w[closes ? 3 : 2] as number);
    hi = Math.max(hi, w[closes ? 3 : 1] as number);
  }
  return lo <= hi ? [lo, hi] : null;
}

describe("property: SeriesPriceSource reads the drawn extent of the main series", () => {
  it(`holds for ${CASES} seeded cases`, () => {
    const rng = mulberry32(0x5e11a1);
    const out = new Float64Array(2);
    for (let c = 0; c < CASES; c += 1) {
      const n = 1 + Math.floor(rng() * 120);
      const ha = rng() < 0.5;
      const { store, ring } = seriesOf(randomBars(rng, 0, n), ha);
      const vp = new ChartViewport(store);
      vp.setPriceInfo(0, store.priceOrigin, store.tickSize);
      const src = new SeriesPriceSource(store, ring, vp, 0);
      const i0 = Math.floor(rng() * (n + 20)) - 10;
      const i1 = i0 + Math.floor(rng() * 60);
      const want = drawn(ring, i0, i1);
      const ok = src.extent(i0, i1, out);
      expect(ok, `seed case ${c}`).toBe(want !== null);
      if (want !== null) expect([out[0], out[1]], `seed case ${c}`).toEqual(want);
      expect(src.minLow()).toBe(drawn(ring, 0, n)?.[0]);
      const k = Math.floor(rng() * n);
      expect(src.close(k)).toBe(store.columns.close[(store.ringHead + k) & (store.capacity - 1)]);
      expect(src.close(n)).toBeNaN();
    }
  });

  it("a series off the time map is read by time and in the pane's price frame", () => {
    const rng = mulberry32(0xa1);
    const out = new Float64Array(2);
    for (let c = 0; c < CASES; c += 1) {
      const main = seriesOf(randomBars(rng, 0, 60), false);
      // A 5-minute series in another frame: price = 49_990 + 0.2 × ticks (main: 50_000 + 0.1 ×).
      const other = randomBars(rng, 0, 12, 5 * STEP);
      const sec = seriesOf({ ...other, priceOrigin: 49_990, tickSize: 0.2 }, rng() < 0.5);
      const vp = new ChartViewport(main.store);
      vp.setPriceInfo(0, 50_000, 0.1);
      const src = new SeriesPriceSource(sec.store, sec.ring, vp, 0);
      const i0 = Math.floor(rng() * 60);
      const i1 = i0 + 1 + Math.floor(rng() * 30);
      // Main bars [i0, i1) span 5-minute bars [floor(i0 / 5), floor((min(i1, 60) - 1) / 5)].
      const want = drawn(sec.ring, Math.floor(i0 / 5), Math.floor((Math.min(i1, 60) - 1) / 5) + 1);
      expect(src.extent(i0, i1, out)).toBe(true);
      const conv = (t: number): number => (49_990 + 0.2 * t - 50_000) / 0.1;
      expect(out[0]).toBe(Math.floor(conv((want as number[])[0] as number)));
      expect(out[1]).toBe(Math.ceil(conv((want as number[])[1] as number)));
      // Cross-frame: the guard's minimum floors the drawn low; the anchor rounds the real close.
      expect(src.minLow()).toBe(
        Math.floor(conv((drawn(sec.ring, 0, 12) as number[])[0] as number)),
      );
      const k = Math.floor(rng() * 60);
      const s = sec.store;
      const real = s.columns.close[(s.ringHead + Math.floor(k / 5)) & (s.capacity - 1)] as number;
      expect(src.close(k)).toBe(Math.round(conv(real)));
    }
  });

  it("closes-only mode (line, area, baseline) reads the close word alone", () => {
    const rng = mulberry32(0xc105e);
    const out = new Float64Array(2);
    for (let c = 0; c < CASES; c += 1) {
      const n = 1 + Math.floor(rng() * 120);
      const { store, ring } = seriesOf(randomBars(rng, 0, n), false); // a line kind's ring is plain
      const vp = new ChartViewport(store);
      vp.setPriceInfo(0, store.priceOrigin, store.tickSize);
      const src = new SeriesPriceSource(store, ring, vp, 0);
      expect(src.minLow()).toBe(drawn(ring, 0, n)?.[0]); // cached in high / low mode first
      src.setClosesOnly(true);
      expect(src.closes).toBe(true);
      const i0 = Math.floor(rng() * (n + 20)) - 10;
      const i1 = i0 + Math.floor(rng() * 60);
      const want = drawn(ring, i0, i1, true);
      expect(src.extent(i0, i1, out), `seed case ${c}`).toBe(want !== null);
      if (want !== null) expect([out[0], out[1]], `seed case ${c}`).toEqual(want);
      // The mode switch drops the cached minimum by itself, before any bump.
      expect(src.minLow(), `seed case ${c}`).toBe(drawn(ring, 0, n, true)?.[0]);
      src.setClosesOnly(false);
      expect(src.minLow(), `seed case ${c}`).toBe(drawn(ring, 0, n)?.[0]);
    }
  });
});

describe("a secondary series off the visible part of the time map", () => {
  const out = new Float64Array(2);
  /** A 60-bar main map (minutes 0 to 59) and a 1-minute secondary from minute `m`, `n` bars. */
  function pair(m: number, n: number): SeriesPriceSource {
    const main = seriesOf(bars(0, 60), false);
    const sec = seriesOf(bars(m, n), false);
    const vp = new ChartViewport(main.store);
    vp.setPriceInfo(0, 50_000, 0.1);
    return new SeriesPriceSource(sec.store, sec.ring, vp, 0);
  }

  it("one that starts after the visible bars contributes nothing there", () => {
    const src = pair(100, 10);
    expect(src.extent(0, 60, out)).toBe(false);
    expect(src.close(59)).toBeNaN();
    expect(src.minLow()).toBe(98); // the guard reads every bar held: bars(100) lows are 98 up
  });

  it("one that starts inside the visible bars reads from its first bar", () => {
    const src = pair(30, 10); // opens 30..39: lows 28..37, highs 33..42
    expect(src.extent(0, 20, out)).toBe(false);
    expect(src.close(29)).toBeNaN();
    expect(src.extent(20, 35, out)).toBe(true);
    expect([out[0], out[1]]).toEqual([28, 37]); // its bars 0..4 (minutes 30..34)
    expect(src.close(34)).toBe(35);
  });

  it("one that ended before the visible bars carries its last bar (timeToIndex, at or before)", () => {
    const src = pair(-20, 10); // minutes -20..-11: opens -20..-11
    expect(src.extent(10, 20, out)).toBe(true);
    expect([out[0], out[1]]).toEqual([-13, -8]); // its last bar only (open -11)
    expect(src.close(10)).toBe(-10);
  });
});

describe("SeriesPriceSource edges", () => {
  it("an empty series contributes nothing, and the version only moves on bump", () => {
    const store = new BarStore();
    const ring = new CandleRing();
    const vp = new ChartViewport(store);
    const src = new SeriesPriceSource(store, ring, vp, 0);
    const out = new Float64Array(2);
    expect(src.extent(0, 10, out)).toBe(false);
    expect(src.minLow()).toBeNaN();
    expect(src.close(0)).toBeNaN();
    expect(src.version).toBe(0);
    src.bump();
    expect(src.version).toBe(1);
  });

  it("minLow follows a bump, and a missing pane or empty time map reads nothing", () => {
    const { store, ring } = seriesOf(bars(0, 10), false);
    const vp = new ChartViewport(store);
    const src = new SeriesPriceSource(store, ring, vp, 0);
    expect(src.minLow()).toBe(-2);
    ring.sync(store, store.append(bars(10, 1, 50_000, 0.1)));
    const lower = { ...bars(11, 1), low: Int32Array.of(-50), open: Int32Array.of(-1) };
    ring.sync(store, store.append({ ...lower, close: Int32Array.of(0) }));
    expect(src.minLow()).toBe(-2); // cached until the runtime bumps it
    src.bump();
    expect(src.minLow()).toBe(-50);
    const out = new Float64Array(2);
    expect(new SeriesPriceSource(store, ring, vp, 3).extent(0, 5, out)).toBe(false);
    const away = new SeriesPriceSource(store, ring, new ChartViewport(), 0);
    expect(away.extent(0, 5, out)).toBe(false);
    expect(away.close(0)).toBeNaN();
  });
});
