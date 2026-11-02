// E12-S08 pre-stage: the volume ring, column twin, extent source and series (E12-D06 §12; plan BQ-2,
// BQ-3, BQ-6, BQ-7, BQ-14). Seeded mulberry32 properties (the package uses no fast-check, README
// BQ-30): the ring equals a reference quantisation bar for bar over random mutations; colour is the
// REAL direction; zero stays a zero-height column, an unavailable bar draws nothing; the extent is
// [0, visible max]; columns sit on the price series' slots; the series is theme-driven.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  CANDLE_DIR,
  CANDLE_PART,
  CandleRing,
  CandleSeries,
  candleRect,
  DEFAULT_QUANTUM,
  GEOM,
  MARK,
  MAX_TICKS,
  PALETTE,
  UNAVAILABLE_TICK,
  VOLUME_UNAVAILABLE,
  VolumeExtentSource,
  VolumeRing,
  VolumeSeries,
  candleDir,
  quantise,
  unavailableMark,
  volumeColor,
  volumeRect,
  volumeTinted,
} from "../../src/layers/index.js";
import { BarStore, type BarBatch } from "../../src/model/index.js";
import { ringBar, THEME } from "./fixtures.js";

const NA = VOLUME_UNAVAILABLE; // the flag bit the caller configures (BQ-7)

function batch(
  rows: readonly (readonly number[])[],
  vols: readonly number[],
  t0 = 0,
  dt = 60e6,
): BarBatch {
  const col = (k: number): Int32Array => Int32Array.from(rows, (r) => r[k] ?? 0);
  return {
    time: Float64Array.from(rows, (_, i) => t0 + i * dt),
    open: col(0),
    high: col(1),
    low: col(2),
    close: col(3),
    volume: Float32Array.from(vols),
    flags: new Uint8Array(rows.length),
    priceOrigin: 0,
    tickSize: 1,
  };
}

function setup(rows: readonly (readonly number[])[], vols: readonly number[], q = 0.5, mask = NA) {
  const store = new BarStore({ initialCapacity: 4 });
  const series = new VolumeSeries(null, q, mask);
  series.sync(store, store.replace(batch(rows, vols)));
  return { store, series, ring: series.ring };
}

/** Pokes the unavailable bit into bar i's flags (the store's own flags refuse bits 4..7). */
function markUnavailable(store: BarStore, i: number): void {
  const p = (store.ringHead + i) & (store.capacity - 1);
  (store.columns.flags as Uint8Array)[p] = NA;
}

describe("quantise and the ring words", () => {
  it("rounds half up, clamps at MAX_TICKS, keeps zero at zero", () => {
    expect([
      quantise(0, 0.5),
      quantise(0.25, 0.5),
      quantise(0.75, 0.5),
      quantise(1.2, 0.5),
    ]).toEqual([0, 1, 2, 2]);
    expect(quantise(1e30, 1e-3)).toBe(MAX_TICKS);
    expect(quantise(0.0004, DEFAULT_QUANTUM)).toBe(0);
  });

  it("refuses a bad quantum or a mask over the ring's meta bits", () => {
    for (const q of [0, -1, Number.NaN, Infinity])
      expect(() => new VolumeRing(q)).toThrow(RangeError);
    expect(() => new VolumeRing(1, 0x10)).toThrow(RangeError);
    expect(() => new VolumeRing(1, 0x100)).toThrow(RangeError);
    expect(() => new VolumeRing(1).setQuantum(0)).toThrow(RangeError);
  });

  it("writes [0, v, 0, v] with the real direction, in the store's own slots", () => {
    const { ring } = setup(
      [
        [10, 12, 9, 11], // up
        [11, 12, 8, 9], // down
        [9, 9, 9, 9], // zero range
        [9, 10, 8, 9], // doji
      ],
      [4, 2.5, 0, 1],
    );
    expect(ringBar(ring, 0)).toEqual([0, 8, 0, 8, CANDLE_DIR.up << 4]);
    expect(ringBar(ring, 1)).toEqual([0, 5, 0, 5, CANDLE_DIR.down << 4]);
    expect(ringBar(ring, 2)).toEqual([0, 0, 0, 0, CANDLE_DIR.zeroRange << 4]);
    expect(ringBar(ring, 3)).toEqual([0, 2, 0, 2, CANDLE_DIR.doji << 4]);
  });

  it("clamps a volume past the ticks window and counts it", () => {
    const { series } = setup([[1, 2, 0, 1]], [3e9], 1);
    expect(series.transform.clamped).toBe(1);
    expect(ringBar(series.ring, 0)[3]).toBe(MAX_TICKS);
  });

  it("matches a reference over random append / patch / prepend / replace sequences", () => {
    for (let seed = 1; seed <= 300; seed += 1) {
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const store = new BarStore({ maxBars: 6 + int(20), initialCapacity: 1 + int(4) });
      const series = new VolumeSeries(null, 0.25, NA);
      let t = 1_000;
      const make = (k: number): BarBatch => {
        const rows = Array.from({ length: k }, () => {
          const lo = int(20) - 10;
          const hi = lo + int(4);
          return [lo + int(hi - lo + 1), hi, lo, lo + int(hi - lo + 1)];
        });
        const b = batch(
          rows,
          rows.map(() => (int(8) === 0 ? 0 : rng() * 50)),
          t,
        );
        t += k * 60e6;
        return b;
      };
      for (let s = 0; s < 12; s += 1) {
        const op = int(4);
        if (op === 0 || store.length === 0) series.sync(store, store.append(make(1 + int(3))));
        else if (op === 1) {
          const k = Math.min(store.length, 1 + int(2));
          const at = int(store.length - k + 1);
          const b = make(k);
          const v = store.view();
          b.time.set(v.time.subarray(at, at + k)); // keep time order with the neighbours
          series.sync(store, store.patch(at, b));
        } else if (op === 2 && store.length + 2 <= store.maxBars) {
          const b = make(2);
          b.time.set(b.time.map((x) => x - 1e12 - s * 1e9));
          series.sync(store, store.prepend(b));
        } else series.sync(store, store.replace(make(1 + int(5))));
        const v = store.view();
        for (let i = 0; i < store.length; i += 1) {
          const o = v.open[i] as number;
          const h = v.high[i] as number;
          const l = v.low[i] as number;
          const c = v.close[i] as number;
          const ticks = quantise(v.volume[i] as number, 0.25);
          expect(ringBar(series.ring, i), `seed ${seed} step ${s} bar ${i}`).toEqual([
            0,
            ticks,
            0,
            ticks,
            candleDir(o, h, l, c) << 4,
          ]);
        }
      }
    }
  });
});

describe("colour select by direction (D06 §12: real open / close, doji neutral)", () => {
  it("up: up row, tinted fill + outline; down: down row, solid; doji and zero range: neutral", () => {
    const marks = [CANDLE_DIR.up, CANDLE_DIR.down, CANDLE_DIR.doji, CANDLE_DIR.zeroRange];
    expect(marks.map((d) => volumeColor(d))).toEqual([
      PALETTE.up,
      PALETTE.down,
      PALETTE.wick,
      PALETTE.wick,
    ]);
    expect(marks.map((d) => volumeTinted(d))).toEqual([true, false, false, false]);
    expect(volumeColor(CANDLE_DIR.up | 0x20)).toBe(PALETTE.up); // other mark bits do not matter
    expect(MARK.dir).toBe(3);
  });

  it("colour does not follow Heikin-Ashi or the previous close", () => {
    // Real bar: down (11 -> 9) although it closes above the previous bar's close.
    const { ring } = setup(
      [
        [1, 2, 0, 1],
        [11, 12, 8, 9],
      ],
      [1, 1],
    );
    expect((ringBar(ring, 1)[4] as number) >> 4).toBe(CANDLE_DIR.down);
  });
});

describe("null and zero volume (BQ-7)", () => {
  it("zero draws a zero-height column; an unavailable bar draws nothing", () => {
    const { store, series } = setup(
      [
        [1, 3, 0, 2],
        [1, 3, 0, 2],
        [1, 3, 0, 2],
      ],
      [0, 5, 5],
    );
    markUnavailable(store, 2);
    series.sync(store, store.patch(2, batch([[1, 3, 0, 2]], [5], 120e6)));
    // the patch rewrote the flag; poke again after it, as the store's put zeroes the column
    markUnavailable(store, 2);
    series.sync(store, { op: "patch", from: 2, to: 3, indexShift: 0 } as never);
    const k = Float32Array.of(10, -0.01, 100, 0, 200, 100);
    const geom = series.geom;
    series.frame(10, 1);
    const out = new Float64Array(4);
    const at = (i: number): number[] => ringBar(series.ring, i);
    volumeRect(0, at(0)[3] as number, (at(0)[4] as number) >> 4, k, 0, 0, geom, out);
    expect(out[3]).toBeLessThanOrEqual(geom[GEOM.hair] as number); // zero: a hairline at most
    expect(out[2]).toBeGreaterThan(0);
    expect(at(2)[3]).toBe(UNAVAILABLE_TICK);
    expect(unavailableMark((at(2)[4] as number) >> 4)).toBe(true);
    expect(unavailableMark((at(0)[4] as number) >> 4)).toBe(false);
    volumeRect(2, at(2)[3] as number, (at(2)[4] as number) >> 4, k, 0, 0, geom, out);
    expect(Array.from(out)).toEqual([0, 0, 0, 0]);
  });

  it("a negative or infinite volume (never through the store) is unavailable, not a column", () => {
    const { store, series, ring } = setup(
      [
        [1, 2, 0, 1],
        [1, 2, 0, 1],
        [1, 2, 0, 1],
      ],
      [1, 1, 1],
      1,
      0,
    );
    const p = (i: number): number => (store.ringHead + i) & (store.capacity - 1);
    (store.columns.volume as Float32Array)[p(0)] = -1;
    (store.columns.volume as Float32Array)[p(1)] = Number.POSITIVE_INFINITY;
    (store.columns.volume as Float32Array)[p(2)] = Number.NaN;
    series.sync(store, { op: "replace", from: 0, to: 3, indexShift: 0 } as never);
    for (let i = 0; i < 3; i += 1) expect(ringBar(ring, i)[3]).toBe(UNAVAILABLE_TICK);
  });
});

describe("autoscale extent (BQ-6)", () => {
  it("is [0, visible max], ignores unavailable bars, and follows the version", () => {
    const { store, series } = setup(
      [
        [1, 2, 0, 1],
        [1, 2, 0, 1],
        [1, 2, 0, 1],
        [1, 2, 0, 1],
      ],
      [1, 9, 3, 7],
      1,
    );
    markUnavailable(store, 1);
    series.sync(store, { op: "patch", from: 0, to: 4, indexShift: 0 } as never);
    const out = new Float64Array(2);
    const e = series.extent;
    expect(e.extent(0, 4, out)).toBe(true);
    expect(Array.from(out)).toEqual([0, 7]); // bar 1 (9) is unavailable
    expect(e.extent(0, 3, out) && out[1]).toBe(3);
    expect(e.extent(-5, 1, out) && out[1]).toBe(1); // clipped to the ring
    expect(e.extent(4, 9, out)).toBe(false);
    expect(e.extent(1, 2, out)).toBe(false); // only the unavailable bar
    expect(e.minLow()).toBe(0);
    const v = e.version;
    series.sync(store, store.patch(0, batch([[1, 2, 0, 1]], [2], 0)));
    expect(e.version).toBe(v + 1);
    expect(new VolumeExtentSource(new CandleRing()).minLow()).toBeNaN();
  });
});

describe("index alignment (BQ-14): columns sit on the price series' slots", () => {
  it("unequal times and a gap_before bar keep column x equal to the candle's x at every index", () => {
    const rows = [
      [10, 12, 9, 11],
      [11, 13, 10, 12],
      [12, 14, 11, 13],
      [13, 15, 12, 14],
    ];
    const store = new BarStore({ initialCapacity: 4 });
    const b = batch(rows, [1, 2, 3, 4]);
    b.time.set([0, 7e6, 5_000e6, 5_001e6]); // renko / range-like: unequal times
    (b.flags as Uint8Array)[2] = 1; // gap_before
    const price = new CandleSeries(new CandleRing());
    const vol = new VolumeSeries(null, 1);
    const r = store.replace(b);
    price.ring.sync(store, r);
    vol.sync(store, r);
    price.frame(12, 2);
    vol.frame(12, 2);
    const k = Float32Array.of(12, -1, 300, 0, 400, 300);
    const [pc, vc] = [new Float64Array(4), new Float64Array(4)];
    for (let i = 0; i < 4; i += 1) {
      const pr = ringBar(price.ring, i);
      candleRect(
        CANDLE_PART.body,
        i,
        pr[0] as number,
        pr[1] as number,
        pr[2] as number,
        pr[3] as number,
        (pr[4] as number) >> 4,
        k,
        0,
        0,
        price.geom,
        pc,
      );
      const vr = ringBar(vol.ring, i);
      volumeRect(i, vr[3] as number, (vr[4] as number) >> 4, k, 0, 0, vol.geom, vc);
      expect([vc[0], vc[2]], `bar ${i}`).toEqual([pc[0], pc[2]]);
    }
    expect([vol.ring.head, vol.ring.length, vol.ring.capacity]).toEqual([
      price.ring.head,
      price.ring.length,
      price.ring.capacity,
    ]);
  });
});

describe("VolumeSeries", () => {
  it("is hidden until the theme has the candle tokens, then drawn; one body block, labelled", () => {
    const { series } = setup([[1, 2, 0, 1]], [1]);
    expect(series.block.label).toBe("series.volume.body");
    expect(series.block.ints[0]).toBe(CANDLE_PART.body);
    expect(series.setTheme({})?.code).toBe("ENGINE_THEME_TOKEN_MISSING");
    expect(series.drawable).toBe(false);
    expect(series.setTheme(THEME)).toBeNull();
    expect(series.drawable).toBe(true);
    const before = Array.from(series.palette);
    expect(series.setTheme({ ...THEME, "color.candle.up": "#ffffff" })).toBeNull();
    expect(Array.from(series.palette)).not.toEqual(before);
    series.frame(8, 2);
    expect(Array.from(series.block.ints)).toEqual([
      CANDLE_PART.body,
      series.ring.head,
      series.ring.capacity - 1,
      1,
    ]);
    expect(series.source).toBe(series.ring);
  });

  it("setQuantum rewrites every column in place, same array", () => {
    const { store, series } = setup(
      [
        [1, 2, 0, 1],
        [1, 2, 0, 2],
      ],
      [1, 2],
      1,
    );
    const data = series.ring.data;
    expect([ringBar(series.ring, 0)[3], ringBar(series.ring, 1)[3]]).toEqual([1, 2]);
    series.setQuantum(store, 0.5);
    expect([ringBar(series.ring, 0)[3], ringBar(series.ring, 1)[3]]).toEqual([2, 4]);
    expect(series.ring.data).toBe(data);
    expect(series.ring.ha).toBe(series.transform);
  });

  it("dispose detaches the node and the sink", () => {
    const { series } = setup([[1, 2, 0, 1]], [1]);
    series.ring.nodes.push("x");
    series.dispose();
    expect([series.ring.nodes.length, series.ring.sink, series.drawable, series.host]).toEqual([
      0,
      null,
      false,
      null,
    ]);
  });
});
