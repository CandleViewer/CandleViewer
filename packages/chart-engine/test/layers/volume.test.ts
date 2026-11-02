// E12-S08 PR 1: the volume ring, `volume` program twin, extent source and series (E12-D06 §12;
// BQ-2, BQ-3, BQ-6, BQ-7, BQ-14). Seeded mulberry32 properties (the package uses no fast-check,
// README BQ-30): the ring equals a reference quantisation bar for bar over random mutations;
// colour is the REAL direction; a doji or zero-range bar is a FULL-height column; zero volume
// draws nothing; an unavailable bar (the engine-internal store bit) is skipped, never a sentinel;
// the extent is [0, visible max] with no margin; a decimated tier is neutral, max per column;
// columns sit on the price series' slots; the quantisation step is required.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { VOLUME } from "../../src/gl/shaders/volume.js";
import {
  CANDLE_DIR,
  CANDLE_PART,
  CandleRing,
  CandleSeries,
  candleRect,
  GEOM,
  MARK,
  MAX_TICKS,
  PALETTE,
  VOLUME_NEUTRAL,
  VOLUME_PART,
  VOLUME_PANE_MARGINS,
  VOLUME_UNAVAILABLE,
  VolumeExtentSource,
  VolumeQuantumError,
  VolumeRing,
  VolumeSeries,
  candleDir,
  maxPerColumn,
  neutralMark,
  quantise,
  unavailableMark,
  volumeColor,
  volumeRect,
  volumeTinted,
} from "../../src/layers/index.js";
import { BAR_FLAG_INTERNAL, BarStore, type BarBatch } from "../../src/model/index.js";
import { ringBar, THEME } from "./fixtures.js";

const K = Float32Array.of(10, -10, 1000, 0, 200, 1000); // u_k, u_viewport (a pane block's floats)

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

function setup(rows: readonly (readonly number[])[], vols: readonly number[], q = 0.5) {
  const store = new BarStore({ initialCapacity: 4 });
  const series = new VolumeSeries(q);
  series.sync(store, store.replace(batch(rows, vols)));
  return { store, series, ring: series.ring };
}

/** One instance's [x, y, w, h] through the twin, from the ring's own words. */
function rectOf(series: VolumeSeries, i: number, k: ArrayLike<number> = K): number[] {
  const out = new Float64Array(4);
  const w = ringBar(series.ring, i);
  volumeRect(i, w[0] as number, (w[4] as number) >> 4, k, 0, 0, series.geom, out);
  return Array.from(out);
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
    expect(quantise(0.0004, 1e-3)).toBe(0);
  });

  it("the quantisation step is REQUIRED: absent, zero, negative, NaN or infinite throws", () => {
    for (const q of [undefined, null, "1", 0, -1, Number.NaN, Infinity]) {
      expect(() => new VolumeRing(q as never)).toThrow(VolumeQuantumError);
      expect(() => new VolumeSeries(q as never)).toThrow(VolumeQuantumError);
    }
    expect(() => new VolumeRing(1).setQuantum(0)).toThrow(VolumeQuantumError);
    expect(() => new VolumeRing(1).setQuantum(Number.NaN)).toThrow(RangeError);
    expect(new VolumeRing(0.25).quantum).toBe(0.25);
  });

  it("writes [v, 0, 0, 0, meta] with the real direction, in the store's own slots", () => {
    const { ring } = setup(
      [
        [10, 12, 9, 11], // up
        [11, 12, 8, 9], // down
        [9, 9, 9, 9], // zero range
        [9, 10, 8, 9], // doji
      ],
      [4, 2.5, 0, 1],
    );
    expect(ringBar(ring, 0)).toEqual([8, 0, 0, 0, CANDLE_DIR.up << 4]);
    expect(ringBar(ring, 1)).toEqual([5, 0, 0, 0, CANDLE_DIR.down << 4]);
    expect(ringBar(ring, 2)).toEqual([0, 0, 0, 0, CANDLE_DIR.zeroRange << 4]);
    expect(ringBar(ring, 3)).toEqual([2, 0, 0, 0, CANDLE_DIR.doji << 4]);
  });

  it("clamps a volume past the ticks window and counts it", () => {
    const { series } = setup([[1, 2, 0, 1]], [3e9], 1);
    expect(series.transform.clamped).toBe(1);
    expect(ringBar(series.ring, 0)[0]).toBe(MAX_TICKS);
  });

  it("a mid-series patch writes exactly the mutated bar (local transform), not to the end", () => {
    const rows = Array.from({ length: 6 }, () => [1, 3, 0, 2]);
    const { store, series, ring } = setup(rows, [1, 2, 3, 4, 5, 6], 1);
    const [written, computed] = [ring.written, series.transform.computed];
    series.sync(store, store.patch(2, batch([[1, 3, 0, 2]], [9], 2 * 60e6)));
    expect([ring.lastFrom, ring.lastTo, ring.written - written]).toEqual([2, 3, 1]);
    expect(series.transform.computed - computed).toBe(1);
    expect(ringBar(ring, 2)[0]).toBe(9);
    expect([ringBar(ring, 3)[0], ringBar(ring, 5)[0]]).toEqual([4, 6]);
  });

  it("matches a reference over random append / patch / prepend / replace sequences", () => {
    for (let seed = 1; seed <= 300; seed += 1) {
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const store = new BarStore({ maxBars: 6 + int(20), initialCapacity: 1 + int(4) });
      const series = new VolumeSeries(0.25);
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
        const op = int(5);
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
        } else if (op === 3) {
          series.sync(store, store.markVolumeNull(int(store.length), 1, int(2) === 0));
        } else series.sync(store, store.replace(make(1 + int(5))));
        const v = store.view();
        for (let i = 0; i < store.length; i += 1) {
          const [o, h, l, c] = [v.open[i] ?? 0, v.high[i] ?? 0, v.low[i] ?? 0, v.close[i] ?? 0];
          const na = ((v.flags[i] as number) & BAR_FLAG_INTERNAL.volumeNull) !== 0;
          const ticks = na ? 0 : quantise(v.volume[i] as number, 0.25);
          const meta =
            ((v.flags[i] as number) & 0x0f) |
            (candleDir(o, h, l, c) << 4) |
            (na ? VOLUME_UNAVAILABLE : 0);
          expect(ringBar(series.ring, i), `seed ${seed} step ${s} bar ${i}`).toEqual([
            ticks,
            0,
            0,
            0,
            meta,
          ]);
        }
      }
    }
  });
});

describe("E12-D06 §12 at every tier the engine has", () => {
  const rows = [
    [10, 12, 9, 11], // up
    [11, 12, 8, 9], // down
    [9, 10, 8, 9], // doji
    [9, 9, 9, 9], // zero range
  ];

  it("L0: colour by the real open / close direction; doji and zero-range neutral wick", () => {
    const marks = [CANDLE_DIR.up, CANDLE_DIR.down, CANDLE_DIR.doji, CANDLE_DIR.zeroRange];
    expect(marks.map(volumeColor)).toEqual([PALETTE.up, PALETTE.down, PALETTE.wick, PALETTE.wick]);
    expect(marks.map(volumeTinted)).toEqual([true, false, false, false]); // up: tint + outline
    expect(volumeColor(CANDLE_DIR.up | 0x20)).toBe(PALETTE.up); // other mark bits do not matter
    const { ring } = setup(rows, [3, 3, 3, 3]);
    expect([0, 1, 2, 3].map((i) => (ringBar(ring, i)[4] as number) >> 4)).toEqual(marks);
  });

  it("L0: colour does not follow Heikin-Ashi or the previous close", () => {
    const { ring } = setup(
      [
        [1, 2, 0, 1],
        [11, 12, 8, 9], // down, though above the previous close
      ],
      [1, 1],
    );
    expect((ringBar(ring, 1)[4] as number) >> 4).toBe(CANDLE_DIR.down);
  });

  it("L0: a doji and a zero-range column are FULL height, like an up or down column", () => {
    const { series } = setup(rows, [4, 4, 4, 4], 1);
    series.frame(10, 1);
    const rects = [0, 1, 2, 3].map((i) => rectOf(series, i));
    // every direction: the same y and height, body wide.
    const [x, y, w, h] = rects[0] as number[];
    expect(h).toBeCloseTo(40, 5); // 4 ticks at 10 px per tick
    expect(w).toBe(series.geom[GEOM.body]);
    for (const r of rects) expect([r[1], r[2], r[3]]).toEqual([y, w, h]);
    expect(rects.map((r) => r[0])).toEqual([
      x,
      (x as number) + 10,
      (x as number) + 20,
      (x as number) + 30,
    ]);
  });

  it("L0: zero volume draws nothing; a tiny volume still draws one hairline", () => {
    const { series } = setup(rows.slice(0, 2), [0, 0.001], 1e-3);
    series.frame(10, 1);
    const fine = Float32Array.of(10, -0.01, 100, 0, 200, 100); // 1 tick is 0.01 px: under a hairline
    expect(rectOf(series, 0, fine)[3]).toBe(0);
    expect(rectOf(series, 1, fine)[3]).toBe(series.geom[GEOM.hair]);
  });

  it("L0: an unavailable bar is skipped (no sentinel); the store refuses the wire bit", () => {
    const { store, series, ring } = setup(rows, [5, 5, 5, 5], 1);
    series.sync(store, store.markVolumeNull(1));
    series.frame(10, 1);
    expect(ringBar(ring, 1)).toEqual([0, 0, 0, 0, (CANDLE_DIR.down << 4) | VOLUME_UNAVAILABLE]);
    expect(rectOf(series, 1)).toEqual([0, 0, 0, 0]);
    expect(rectOf(series, 0)[3]).toBeGreaterThan(0);
    expect(((ringBar(ring, 1)[4] as number) >> 4) & 4).toBe(4);
    expect(unavailableMark((ringBar(ring, 1)[4] as number) >> 4)).toBe(true);
    // Clearing it brings the column back; a host batch can never set the engine-internal bit.
    series.sync(store, store.markVolumeNull(1, 1, false));
    expect(ringBar(ring, 1)[0]).toBe(5);
    const bad = batch([[1, 2, 0, 1]], [1], 9e9);
    (bad.flags as Uint8Array)[0] = BAR_FLAG_INTERNAL.volumeNull;
    expect(() => store.append(bad)).toThrow();
    for (const [at, n] of [
      [-1, 1],
      [0, 9],
    ] as const) {
      expect(() => store.markVolumeNull(at, n)).toThrow();
    }
  });

  it("the engine-internal bit is clear of the wire flags and the ring's dir bits", () => {
    expect(BAR_FLAG_INTERNAL.volumeNull).toBe(0x40);
    expect(BAR_FLAG_INTERNAL.volumeNull & 0x0f).toBe(0); // 23 kind 4: wire flags use bit 0..3
    expect(BAR_FLAG_INTERNAL.volumeNull & (MARK.dir << 4)).toBe(0); // 4..5 are dir
    expect(VOLUME_NEUTRAL).toBe(0x80);
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
    );
    const p = (i: number): number => (store.ringHead + i) & (store.capacity - 1);
    (store.columns.volume as Float32Array)[p(0)] = -1;
    (store.columns.volume as Float32Array)[p(1)] = Number.POSITIVE_INFINITY;
    (store.columns.volume as Float32Array)[p(2)] = Number.NaN;
    series.sync(store, { op: "replace", from: 0, to: 3, indexShift: 0 } as never);
    for (let i = 0; i < 3; i += 1) {
      expect(ringBar(ring, i)[0]).toBe(0);
      expect(unavailableMark((ringBar(ring, i)[4] as number) >> 4)).toBe(true);
    }
  });

  it("decimated tier: every column neutral wick, solid, no direction (setNeutral rewrites in place)", () => {
    const { store, series, ring } = setup(rows, [4, 4, 4, 4], 1);
    const data = ring.data;
    series.setNeutral(store, true);
    expect(ring.data).toBe(data);
    for (let i = 0; i < 4; i += 1) {
      const mark = (ringBar(ring, i)[4] as number) >> 4;
      expect([volumeColor(mark), volumeTinted(mark), neutralMark(mark)]).toEqual([
        PALETTE.wick,
        false,
        true,
      ]);
    }
    series.setNeutral(store, false);
    expect(volumeColor((ringBar(ring, 0)[4] as number) >> 4)).toBe(PALETTE.up);
  });

  it("decimated tier reduction (the twin's helper; decimation itself is E12-S09): max per column", () => {
    const flat = Array.from({ length: 7 }, () => [1, 2, 0, 1]);
    const store = new BarStore({ initialCapacity: 8 });
    const series = new VolumeSeries(1);
    series.sync(store, store.replace(batch(flat, [3, 9, 1, 2, 2, 7, 5])));
    series.sync(store, store.markVolumeNull(1)); // the 9 is unavailable: it does not count
    series.sync(store, store.markVolumeNull(3, 2));
    const ticks: number[] = [];
    const metas: number[] = [];
    for (let i = 0; i < 7; i += 1) {
      const w = ringBar(series.ring, i);
      ticks.push(w[0] as number);
      metas.push(w[4] as number);
    }
    const out = new Int32Array(4);
    // columns of 3: [3, -, 1] -> 3; [-, -, 7] -> 7; [5] -> 5. Per 2: [3,-] [1,-] [-,7] [5].
    expect([maxPerColumn(ticks, metas, 3, out), Array.from(out.subarray(0, 3))]).toEqual([
      3,
      [3, 7, 5],
    ]);
    expect([maxPerColumn(ticks, metas, 2, out), Array.from(out)]).toEqual([4, [3, 1, 7, 5]]);
    metas[0] = metas[1] = VOLUME_UNAVAILABLE;
    expect(maxPerColumn(ticks, metas, 2, out) && out[0]).toBe(-1); // nothing counts: unavailable
    expect(maxPerColumn(ticks, metas, 0, out)).toBe(7); // per < 1 reads as 1
  });

  it("the shader mirrors the twin: no dir>=2 height rule, no sentinel, a skip on the unavailable bit", () => {
    const v = VOLUME.vertex;
    expect(v).not.toContain("dir >= 2) {"); // the candle shader's doji hairline branch
    expect(v).toContain("(mark & 4) != 0"); // the skip bit: unavailable collapses the instance
    expect(v).toContain("(mark & 8) != 0 || dir >= 2"); // neutral: a tier, doji, zero range
    expect(v).toContain("a_vol.x == 0 ? 0.0 : max(max(y0, y1) - top, h)"); // full height, zero none
    expect(v).not.toMatch(/1073741824|-2\.0e9|u_log/); // no sentinel position, no log mix
  });
});

describe("autoscale extent (BQ-6): scale 0 to the visible maximum, no margin", () => {
  it("is exactly [0, visible max], ignores unavailable bars, and follows the version", () => {
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
    series.sync(store, store.markVolumeNull(1));
    const out = new Float64Array(2);
    const e = series.extent;
    expect(e.extent(0, 4, out)).toBe(true);
    expect(Array.from(out)).toEqual([0, 7]); // bar 1 (9) is unavailable; no margin on the max
    expect(e.extent(0, 3, out) && out[1]).toBe(3);
    expect(e.extent(-5, 1, out) && out[1]).toBe(1); // clipped to the ring
    expect(e.extent(4, 9, out)).toBe(false);
    expect(e.extent(1, 2, out)).toBe(false); // only the unavailable bar
    expect(e.minLow()).toBe(0);
    expect(VOLUME_PANE_MARGINS).toEqual({ top: 0, bottom: 0 });
    const v = e.version;
    series.sync(store, store.patch(0, batch([[1, 2, 0, 1]], [2], 0)));
    expect(e.version).toBe(v + 1);
    expect(new VolumeExtentSource(new CandleRing()).minLow()).toBeNaN();
  });

  it("an all-zero window is [0, 0], never a 1e-3 fallback", () => {
    const { series } = setup([[1, 2, 0, 1]], [0], 1);
    const out = new Float64Array(2);
    expect(series.extent.extent(0, 1, out)).toBe(true);
    expect(Array.from(out)).toEqual([0, 0]);
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
    const vol = new VolumeSeries(1);
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
      volumeRect(i, vr[0] as number, (vr[4] as number) >> 4, k, 0, 0, vol.geom, vc);
      expect([vc[0], vc[2]], `bar ${i}`).toEqual([pc[0], pc[2]]);
    }
    // gap_before (D06 §11.1 / §8.2): the flag rides in meta bit 0 and moves no column: the same
    // bars without it sit at the same x, width and height (the seam is the price series' alone).
    expect(
      (vol.ring.ints[((vol.ring.head + 2) & (vol.ring.capacity - 1)) * 5 + 4] as number) & 1,
    ).toBe(1);
    const plain = new VolumeSeries(1);
    const store2 = new BarStore({ initialCapacity: 4 });
    const b2 = batch(rows, [1, 2, 3, 4]);
    b2.time.set([0, 7e6, 5_000e6, 5_001e6]);
    plain.sync(store2, store2.replace(b2));
    plain.frame(12, 2);
    for (let i = 0; i < 4; i += 1) {
      const [a, c] = [new Float64Array(4), new Float64Array(4)];
      const [wa, wb] = [ringBar(vol.ring, i), ringBar(plain.ring, i)];
      volumeRect(i, wa[0] as number, (wa[4] as number) >> 4, k, 0, 0, vol.geom, a);
      volumeRect(i, wb[0] as number, (wb[4] as number) >> 4, k, 0, 0, plain.geom, c);
      expect(Array.from(a), `bar ${i}`).toEqual(Array.from(c));
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
    expect(series.block.ints[0]).toBe(VOLUME_PART);
    expect(series.setTheme({})?.code).toBe("ENGINE_THEME_TOKEN_MISSING");
    expect(series.drawable).toBe(false);
    expect(series.setTheme(THEME)).toBeNull();
    expect(series.drawable).toBe(true);
    const before = Array.from(series.palette);
    expect(series.setTheme({ ...THEME, "color.candle.up": "#ffffff" })).toBeNull();
    expect(Array.from(series.palette)).not.toEqual(before);
    series.frame(8, 2);
    expect(Array.from(series.block.ints)).toEqual([
      VOLUME_PART,
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
    expect([ringBar(series.ring, 0)[0], ringBar(series.ring, 1)[0]]).toEqual([1, 2]);
    series.setQuantum(store, 0.5);
    expect([ringBar(series.ring, 0)[0], ringBar(series.ring, 1)[0]]).toEqual([2, 4]);
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
