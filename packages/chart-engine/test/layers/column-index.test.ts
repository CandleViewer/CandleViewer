// E12-S09 AC6 and BQ-06 (#421; 26 §3.6, E12-D06 §5.5 / §11.1 / §12). The L2 grid is index
// space: bar i is in device column floor((i + 0.5 − leftIndex) · pxPerBar), so Renko
// (`isTimeAligned` false) buckets by brick index, and a time gap between bricks moves no bucket;
// such a series never draws the seam. `foldVolumeMax` is the volume sub-pane's neutral max per
// column for E12-S08: max, not sum; zero volume; columns outside `out` skipped; no allocation.
import { describe, expect, it } from "vitest";
import { CandleRing, CandleSeries, ColumnEntries, foldVolumeMax } from "../../src/layers/index.js";
import { BarStore } from "../../src/model/index.js";
import { foldOracle, rowsBatch } from "./column-oracle.js";

const BRICKS = Array.from({ length: 16 }, (_, i) => [100 + i, 101 + i, 100 + i, 101 + i, i % 5]);

function store(times?: Float64Array, flags?: Uint8Array): BarStore {
  const s = new BarStore();
  s.append(rowsBatch(BRICKS, flags, times));
  return s;
}

describe("AC6: Renko at L2 buckets by brick index, never by time", () => {
  it("bricks hours apart fold into the same columns as evenly spaced ones", () => {
    const even = store();
    const gappy = store(Float64Array.from(BRICKS, (_, i) => i * 60e6 + (i >= 7 ? 9 * 3600e6 : 0)));
    const entries = (s: BarStore): number[] => {
      const e = new ColumnEntries(8);
      e.write(foldOracle(s, 0, 0.5, s.length, 8));
      return Array.from(e.ints.subarray(0, e.count * 5));
    };
    expect(entries(gappy)).toEqual(entries(even));
    const vol = (s: BarStore): number[] => {
      const out = new Float32Array(8);
      foldVolumeMax(s, 0, 0.5, 0, s.length, 0, out);
      return Array.from(out);
    };
    expect(vol(gappy)).toEqual(vol(even));
  });

  it("an index-spaced series draws no seam at L2, a gap flag or not", () => {
    const s = store(
      undefined,
      Uint8Array.from(BRICKS, (_, i) => (i === 8 ? 1 : 0)),
    );
    const ring = new CandleRing();
    const c = new CandleSeries(ring);
    ring.sync(s, { op: "replace", from: 0, to: s.length, indexShift: 0 });
    c.timeAligned = false;
    c.frame(0.5, 1, 0, 15, 0, 0, 2, new ColumnEntries(8));
    expect(c.blocks[2]?.instances).toBe(0);
  });
});

describe("foldVolumeMax (BQ-06): the neutral max volume per device column", () => {
  it("max per column (not the sum), zero volume kept, out zeroed first", () => {
    const s = store();
    const out = new Float32Array(10).fill(7);
    expect(foldVolumeMax(s, 0, 0.5, 0, s.length, 0, out)).toBe(8);
    expect(Array.from(out)).toEqual([1, 3, 4, 2, 4, 1, 3, 4, 0, 0]);
  });

  it("skips columns outside out; a pan offset shifts the buckets", () => {
    const s = store();
    const out = new Float32Array(3);
    expect(foldVolumeMax(s, 0, 0.5, 0, s.length, 2, out)).toBe(3);
    expect(Array.from(out)).toEqual([4, 2, 4]);
    expect(foldVolumeMax(s, 1, 0.5, 0, s.length, 0, out)).toBe(3);
    expect(Array.from(out)).toEqual([2, 4, 1]);
  });

  it("clamps: a non-finite or non-positive grid writes nothing; from / to clamp to the store", () => {
    const s = store();
    const out = new Float32Array(4);
    for (const px of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(foldVolumeMax(s, 0, px, 0, 16, 0, out)).toBe(0);
    }
    expect(foldVolumeMax(s, Number.NaN, 1, 0, 16, 0, out)).toBe(0);
    expect(foldVolumeMax(s, 0, 1, Number.NaN, Number.NaN, 0, out)).toBe(0);
    expect(foldVolumeMax(s, 0, 1, -5, 1e9, 0, out)).toBe(4);
    expect(Array.from(out)).toEqual([0, 1, 2, 3]);
  });
});
