// E11-T03 FootprintStore and HeatmapRing: the prefix-sum scenario by name, rejections, the ring.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  type FootprintBatch,
  FootprintStore,
  HeatmapRing,
  ModelRejection,
} from "../../src/model/index.js";

function footprint(bars: number, maxCells: number, seed = 7): FootprintBatch {
  const rng = mulberry32(seed);
  const offsets = new Uint32Array(bars + 1);
  for (let b = 0; b < bars; b += 1)
    offsets[b + 1] = (offsets[b] ?? 0) + Math.floor(rng() * (maxCells + 1));
  const n = offsets[bars] ?? 0;
  const price = new Int32Array(n);
  for (let b = 0; b < bars; b += 1) {
    for (let i = offsets[b] ?? 0, p = b; i < (offsets[b + 1] ?? 0); i += 1, p += 1) price[i] = p;
  }
  const vol = Float32Array.from(price, (p) => p % 13);
  return {
    barIndexOffsets: offsets,
    cellPriceLevel: price,
    cellBidVol: vol,
    cellAskVol: vol.map((v) => v + 1),
    cellTradeCount: Uint16Array.from(price, (p) => p % 5),
    priceOrigin: 50_000,
    tickSize: 0.5,
  };
}

const reasonOf = (fn: () => unknown): string => {
  try {
    fn();
  } catch (e) {
    if (e instanceof ModelRejection) return e.reason;
    throw e;
  }
  return "accepted";
};

describe("Scenario: Prefix sums address footprint cells in O(1)", () => {
  it("bar 12 345 of 20 000 × up to 40 cells is a subarray view between its offsets, no copy", () => {
    const store = new FootprintStore();
    const data = footprint(20_000, 40);
    expect({ ...store.replace(data) }).toEqual({
      op: "replace",
      from: 0,
      to: store.cellCount,
      indexShift: 0,
    });
    const [from, to] = [store.offsets[12_345] ?? 0, store.offsets[12_346] ?? 0];
    const cells = store.cellsFor(12_345);
    expect(cells?.priceLevel.buffer).toBe(store.priceLevel.buffer);
    expect([cells?.priceLevel.byteOffset, cells?.priceLevel.length]).toEqual([from * 4, to - from]);
    expect(cells?.bidVol.buffer).toBe(store.bidVol.buffer);
    expect(Array.from(cells?.askVol ?? [])).toEqual(Array.from(data.cellAskVol.subarray(from, to)));
    expect([store.cellsFor(20_000), store.cellsFor(-1), store.bars]).toEqual([null, null, 20_000]);
    expect(store.bytes).toBe(store.cellCount * 18 + 20_001 * 4);
  });
});

describe("FootprintStore rejects a corrupt batch wholesale", () => {
  const base = footprint(4, 3, 3);
  const cases: [string, string, FootprintBatch][] = [
    [
      "offsets not starting at 0",
      "offsets",
      { ...base, barIndexOffsets: Uint32Array.of(1, 1, 1, 1, 9) },
    ],
    [
      "offsets decreasing",
      "offsets",
      { ...base, barIndexOffsets: Uint32Array.of(0, 3, 1, 4, base.cellPriceLevel.length) },
    ],
    [
      "offsets not ending at the cell count",
      "offsets",
      { ...base, barIndexOffsets: Uint32Array.of(0, 0, 0, 0, 0) },
    ],
    [
      "offsets overrunning the cells",
      "offsets",
      { ...base, barIndexOffsets: Uint32Array.of(0, 1e9, 1e9, 1e9, base.cellPriceLevel.length) },
    ],
    ["more bars than maxBars", "ceiling", { ...base, barIndexOffsets: new Uint32Array(200_002) }],
    ["unequal columns", "length", { ...base, cellTradeCount: new Uint16Array(0) }],
    ["no offsets at all", "length", { ...base, barIndexOffsets: new Uint32Array(0) }],
    ["a NaN volume", "non_finite", { ...base, cellBidVol: base.cellBidVol.map(() => NaN) }],
    ["unsorted levels", "order", { ...base, cellPriceLevel: base.cellPriceLevel.map(() => 1) }],
    [
      "a level column that is not Int32Array",
      "type",
      {
        ...base,
        cellPriceLevel: Float64Array.from(
          base.cellPriceLevel,
          () => 2 ** 40,
        ) as unknown as Int32Array,
      },
    ],
    [
      "a bid column that is not Float32Array (1e39)",
      "type",
      {
        ...base,
        cellBidVol: Float64Array.from(base.cellBidVol, () => 1e39) as unknown as Float32Array,
      },
    ],
    ["tickSize NaN", "non_finite", { ...base, tickSize: NaN }],
  ];
  it.each(cases)("%s", (_name, reason, batch) => {
    const store = new FootprintStore();
    store.replace(base);
    const before = [store.priceLevel, store.offsets, store.bidVol];
    expect(reasonOf(() => store.replace(batch))).toBe(reason);
    const after = [store.priceLevel, store.offsets, store.bidVol];
    expect(after.map((a, i) => a === before[i])).toEqual([true, true, true]);
    expect(store.counters.rejectedMutations[reason as "order"]).toBe(1);
  });

  it("a declared cell count over the ceiling is refused before any allocation", () => {
    const store = new FootprintStore({ maxCells: 4 });
    expect(reasonOf(() => store.replace(footprint(10, 3)))).toBe("ceiling");
    expect(store.cellCount).toBe(0);
  });
});

describe("HeatmapRing descriptor", () => {
  it("claims one column per push and wraps the 2048-column ring, oldest overwritten", () => {
    const ring = new HeatmapRing();
    ring.setPriceAxis(50_000, 0.5);
    for (let c = 0; c < 2_048; c += 1) ring.push(c);
    expect([ring.writeCol, ring.filled, ring.rows]).toEqual([0, 2_048, 512]);
    expect({ ...ring.push(5_000) }).toEqual({ op: "append", from: 0, to: 1, indexShift: 0 });
    expect([ring.colTime[0], ring.colTime[1], ring.filled]).toEqual([5_000, 1, 2_048]);
    expect(ring.bytes).toBe(2_048 * 512 * 4 + 2_048 * 8);
  });

  it("refuses a non-finite or older column and a bad price axis", () => {
    const ring = new HeatmapRing();
    ring.push(10);
    expect([reasonOf(() => ring.push(NaN)), reasonOf(() => ring.push(9))]).toEqual([
      "non_finite",
      "order",
    ]);
    expect(reasonOf(() => ring.setPriceAxis(0, 0))).toBe("non_finite");
    expect([ring.writeCol, ring.priceStep]).toEqual([1, 0]);
  });
});
