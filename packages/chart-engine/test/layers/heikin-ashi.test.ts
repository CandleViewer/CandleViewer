// E12-S07 Heikin-Ashi (E12-D06 §3.3; BQ-2 seed at the store's first bar, BQ-3 a float64 HaRing
// written into the series' ring, BQ-4 round half up on write): a hand-checked reference vector,
// a seeded twin property against a plain float64 recurrence, the incremental writes (an append
// or a forming update transforms one bar), eviction stability and the in-place switch.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  CANDLE_DIR,
  CANDLE_META,
  CandleRing,
  CandleSeries,
  HaRing,
  roundHalfUp,
} from "../../src/layers/index.js";
import { type BarBatch, BarStore } from "../../src/model/index.js";
import { ringBar, storeBar } from "./fixtures.js";

function batch(rows: readonly (readonly number[])[], t0 = 0, flags?: number[]): BarBatch {
  const col = (k: number): Int32Array => Int32Array.from(rows, (r) => r[k] ?? 0);
  return {
    time: Float64Array.from(rows, (_, i) => t0 + i * 60e6),
    open: col(0),
    high: col(1),
    low: col(2),
    close: col(3),
    volume: new Float32Array(rows.length).fill(1),
    ...(flags && { flags: Uint8Array.from(flags) }),
    priceOrigin: 0,
    tickSize: 1,
  };
}

/** The twin: D06 §3.3 in float64 over bars [0, n), seeded at bar 0, rounded half up at the end. */
function reference(rows: readonly (readonly number[])[]): number[][] {
  let po = 0;
  let pc = 0;
  return rows.map(([o = 0, h = 0, l = 0, c = 0], i) => {
    const fc = (o + h + l + c) / 4;
    const fo = i === 0 ? (o + c) / 2 : (po + pc) / 2;
    [po, pc] = [fo, fc];
    const [ro, rc] = [roundHalfUp(fo), roundHalfUp(fc)];
    return [ro, Math.max(h, ro, rc), Math.min(l, ro, rc), rc];
  });
}

const haBars = (ring: CandleRing): number[][] =>
  Array.from({ length: ring.length }, (_, i) => ringBar(ring, i).slice(0, 4));

function haRing(rows: readonly (readonly number[])[], maxBars?: number) {
  const store = new BarStore({ initialCapacity: 4, ...(maxBars && { maxBars }) });
  const ring = new CandleRing();
  const series = new CandleSeries(ring);
  series.setKind("candles", true, store);
  ring.sync(store, store.append(batch(rows)));
  return { store, ring, series, ha: ring.ha as HaRing };
}

const ROWS = [
  [100, 110, 96, 106],
  [106, 112, 104, 111],
  [111, 113, 101, 102],
  [102, 104, 95, 96],
  [96, 99, 94, 98],
];

describe("Heikin-Ashi transform (D06 §3.3)", () => {
  it("rounds half up on the tick grid (BQ-4)", () => {
    expect([2.5, -2.5, 108.25, 106.75, -0.5, 7].map(roundHalfUp)).toEqual([3, -2, 108, 107, 0, 7]);
  });

  it("matches the hand-checked reference vector, ticks exact, dir from the HA candle", () => {
    // HA close (O+H+L+C)/4: 103, 108.25, 106.75, 99.25, 96.75; HA open seeded (O+C)/2 = 103,
    // then (103+103)/2 = 103, (103+108.25)/2 = 105.625, (105.625+106.75)/2 = 106.1875,
    // (106.1875+99.25)/2 = 102.71875; high / low include the HA open and close.
    const { ring } = haRing(ROWS);
    expect(haBars(ring)).toEqual([
      [103, 110, 96, 103],
      [103, 112, 103, 108],
      [106, 113, 101, 107],
      [106, 106, 95, 99],
      [103, 103, 94, 97],
    ]);
    const dirs = Array.from({ length: 5 }, (_, i) => ((ringBar(ring, i)[4] ?? 0) >> 4) & 3);
    const { up, down, doji } = CANDLE_DIR;
    expect(dirs).toEqual([doji, up, up, down, down]);
  });

  it("keeps the store's real prices and flags (R-4): only the ring holds HA values", () => {
    const { store, ring } = haRing(ROWS);
    expect(Array.from({ length: 5 }, (_, i) => storeBar(store, i).slice(0, 4))).toEqual(ROWS);
    expect(ringBar(ring, 0)[1]).toBe(110);
    const flagged = haRing([[1, 2, 0, 1]]);
    flagged.ring.sync(
      flagged.store,
      flagged.store.append(batch([[1, 3, 0, 2]], 60e6, [CANDLE_META.flags & 1])),
    );
    expect((ringBar(flagged.ring, 1)[4] ?? 0) & CANDLE_META.flags).toBe(1);
  });

  it("twin property: seeded appends, forming updates, patches and prepends equal the reference", () => {
    for (let seed = 1; seed <= 40; seed += 1) {
      const rnd = mulberry32(seed);
      const bar = (): number[] => {
        const o = Math.floor(rnd() * 2_000) - 1_000;
        const c = o + Math.floor(rnd() * 41) - 20;
        return [
          o,
          Math.max(o, c) + Math.floor(rnd() * 9),
          Math.min(o, c) - Math.floor(rnd() * 9),
          c,
        ];
      };
      const rows = Array.from({ length: 3 + Math.floor(rnd() * 10) }, bar);
      let t0 = 0;
      const { store, ring } = haRing(rows);
      for (let step = 0; step < 30; step += 1) {
        const op = Math.floor(rnd() * 4);
        if (op === 0) {
          const add = Array.from({ length: 1 + Math.floor(rnd() * 3) }, bar);
          ring.sync(store, store.append(batch(add, (t0 + rows.length) * 60e6)));
          rows.push(...add);
        } else if (op === 1) {
          const last = bar(); // the forming bar: same time, merged
          ring.sync(store, store.append(batch([last], (t0 + rows.length - 1) * 60e6), true));
          rows[rows.length - 1] = last;
        } else if (op === 2) {
          const at = Math.floor(rnd() * rows.length);
          const fix = bar();
          ring.sync(store, store.patch(at, batch([fix], (t0 + at) * 60e6)));
          rows[at] = fix;
        } else {
          const k = 1 + Math.floor(rnd() * 3);
          const older = Array.from({ length: k }, bar);
          t0 -= k;
          ring.sync(store, store.prepend(batch(older, t0 * 60e6)));
          rows.unshift(...older);
        }
        expect(haBars(ring), `seed ${seed} step ${step} op ${op}`).toEqual(reference(rows));
      }
    }
  });
});

describe("Heikin-Ashi incremental writes", () => {
  it("an append transforms and uploads the one new bar", () => {
    const { store, ring, ha } = haRing(ROWS);
    const [written, computed] = [ring.written, ha.computed];
    ring.sync(store, store.append(batch([[98, 101, 97, 100]], 5 * 60e6)));
    expect([ring.written - written, ha.computed - computed]).toEqual([1, 1]);
    expect([ring.lastFrom, ring.lastTo]).toEqual([5, 6]);
  });

  it("a forming update rewrites the last bar only, and the same update twice is idempotent", () => {
    const { store, ring, ha } = haRing(ROWS);
    const live = (): BarBatch => batch([[96, 100, 94, 99]], 4 * 60e6);
    const computed = ha.computed;
    ring.sync(store, store.append(live(), true));
    const once = haBars(ring);
    ring.sync(store, store.append(live(), true));
    expect(haBars(ring)).toEqual(once);
    expect([ha.computed - computed, ring.lastFrom, ring.lastTo]).toEqual([2, 4, 5]);
  });

  it("a patch recomputes from the patched bar to the end, never before it", () => {
    const { store, ring } = haRing(ROWS);
    const before = haBars(ring);
    ring.sync(store, store.patch(2, batch([[111, 115, 100, 112]], 2 * 60e6)));
    expect([ring.lastFrom, ring.lastTo]).toEqual([2, 5]);
    expect(haBars(ring).slice(0, 2)).toEqual(before.slice(0, 2));
  });

  it("an eviction keeps the bars held at their values (BQ-2: no reseed)", () => {
    const rows = Array.from({ length: 8 }, (_, i) => [100 + i, 106 + i, 95 + i, 103 + (i % 3)]);
    const { store, ring } = haRing(rows, 8);
    const before = haBars(ring);
    ring.sync(store, store.append(batch([[110, 115, 108, 112]], 8 * 60e6)));
    expect(haBars(ring).slice(0, 7)).toEqual(before.slice(1));
    expect(ring.lastTo - ring.lastFrom).toBe(1);
  });
});

describe("Heikin-Ashi switch (in place)", () => {
  it("turns on and off over the same array; off frees the HaRing and restores the real bars", () => {
    const store = new BarStore({ initialCapacity: 8 });
    const ring = new CandleRing();
    const series = new CandleSeries(ring);
    ring.sync(store, store.append(batch(ROWS)));
    const data = ring.data;
    series.setKind("candles", true, store);
    expect([ring.data, series.heikinAshi, ring.lastFrom, ring.lastTo]).toEqual([data, true, 0, 5]);
    expect(haBars(ring)).toEqual(reference(ROWS));
    series.setKind("candles", false, store);
    expect([ring.data, ring.ha, series.heikinAshi]).toEqual([data, null, false]);
    expect(Array.from({ length: 5 }, (_, i) => ringBar(ring, i))).toEqual(
      Array.from({ length: 5 }, (_, i) => storeBar(store, i)),
    );
    const written = ring.written;
    series.setKind("candles", false, store); // no change: no write
    expect(ring.written).toBe(written);
  });

  it("a reallocated store is rewritten, and HA reseeds from its first bar", () => {
    const { store, ring } = haRing(ROWS);
    const rewrites = ring.rewrites;
    ring.sync(store, store.replace(batch(ROWS.slice(2))));
    expect(ring.rewrites).toBe(rewrites + 1);
    expect(haBars(ring)).toEqual(reference(ROWS.slice(2)));
  });

  it("turning on before the first sync takes the store's columns then", () => {
    const store = new BarStore({ initialCapacity: 8 });
    store.append(batch(ROWS));
    const ring = new CandleRing();
    new CandleSeries(ring).setKind("candles", true, store);
    expect(haBars(ring)).toEqual(reference(ROWS));
  });
});
