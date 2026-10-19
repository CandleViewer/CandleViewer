import { describe, expect, it } from "vitest";
import {
  selectLod,
  decimateMinMax,
  LOD_L0_THRESHOLD_PX,
  LOD_L1_THRESHOLD_PX,
} from "../../../bench/scenes/lod.mjs";
import { BarStore } from "../../../bench/scenes/bar-store.mjs";

describe("LOD selection (E06-K02 throwaway prototype) — §3.6", () => {
  it("selects L0 at wide spacing, L1 mid, L2 narrow, with no previous level", () => {
    expect(selectLod(10, null)).toBe("L0");
    expect(selectLod(2, null)).toBe("L1");
    expect(selectLod(0.5, null)).toBe("L2");
  });

  it("applies +/-15% hysteresis: does not leave L0 just inside the dead band", () => {
    // Threshold is 3px; leaving L0 requires dropping below 3 * 0.85 = 2.55.
    const justInside = LOD_L0_THRESHOLD_PX * 0.9; // 2.7, inside the dead band
    expect(selectLod(justInside, "L0")).toBe("L0");
  });

  it("applies hysteresis: does leave L0 just outside the dead band", () => {
    const justOutside = LOD_L0_THRESHOLD_PX * 0.8; // 2.4, outside the dead band
    expect(selectLod(justOutside, "L0")).not.toBe("L0");
  });

  it("drops from L0 straight to L2 when spacing falls below the L1 threshold (a zoom-out jump)", () => {
    expect(selectLod(LOD_L1_THRESHOLD_PX * 0.5, "L0")).toBe("L2");
  });

  it("does not re-enter L0 from L1 until spacing rises above the enter threshold", () => {
    const justBelowEnter = LOD_L0_THRESHOLD_PX * 1.1; // 3.3, below the 1.15x enter bound
    expect(selectLod(justBelowEnter, "L1")).toBe("L1");
    const justAboveEnter = LOD_L0_THRESHOLD_PX * 1.2; // 3.6, above the 1.15x enter bound
    expect(selectLod(justAboveEnter, "L1")).toBe("L0");
  });

  it("L1 boundary hysteresis behaves symmetrically", () => {
    const justInside = LOD_L1_THRESHOLD_PX * 0.9;
    expect(selectLod(justInside, "L1")).toBe("L1");
    const justOutside = LOD_L1_THRESHOLD_PX * 0.8;
    expect(selectLod(justOutside, "L1")).toBe("L2");
  });
});

describe("decimateMinMax (E06-K02) — spike preservation", () => {
  it("preserves isolated single-bar high/low extremes when zoomed out to L2", () => {
    const store = new BarStore({ capacity: 1000 });
    const bars = Array.from({ length: 500 }, (_, i) => ({
      tOpenMs: i * 60_000,
      o: 100,
      h: 105,
      l: 95,
      c: 100,
      v: 10,
    }));
    // Plant deliberate single-bar extremes that a naive "every Nth bar"
    // sampling would miss.
    bars[123] = { tOpenMs: 123 * 60_000, o: 100, h: 999, l: 95, c: 100, v: 10 };
    bars[377] = { tOpenMs: 377 * 60_000, o: 100, h: 105, l: -500, c: 100, v: 10 };
    store.appendBars(bars);

    const columns = decimateMinMax(store, 0, 500, 50); // 10 bars per column
    const maxHigh = Math.max(...columns.map((c) => c.high));
    const minLow = Math.min(...columns.map((c) => c.low));
    expect(maxHigh).toBe(999);
    expect(minLow).toBe(-500);
  });

  it("every column's high/low bounds every bar it covers (no silent narrowing)", () => {
    const store = new BarStore({ capacity: 200 });
    const bars = Array.from({ length: 200 }, (_, i) => ({
      tOpenMs: i * 60_000,
      o: i,
      h: i + (i % 17 === 0 ? 1000 : 3),
      l: i - (i % 23 === 0 ? 1000 : 3),
      c: i,
      v: 1,
    }));
    store.appendBars(bars);
    const columns = decimateMinMax(store, 0, 200, 20);
    for (const col of columns) {
      let expectedHigh = -Infinity;
      let expectedLow = Infinity;
      for (let i = col.startIndex; i < col.endIndex; i += 1) {
        const h = (store.high as Float32Array)[i] as number;
        const l = (store.low as Float32Array)[i] as number;
        if (h > expectedHigh) expectedHigh = h;
        if (l < expectedLow) expectedLow = l;
      }
      expect(col.high).toBe(expectedHigh);
      expect(col.low).toBe(expectedLow);
    }
  });

  it("returns no columns for an empty range", () => {
    const store = new BarStore({ capacity: 10 });
    store.appendBars([{ tOpenMs: 0, o: 1, h: 2, l: 0, c: 1, v: 1 }]);
    expect(decimateMinMax(store, 5, 5, 10)).toEqual([]);
  });
});
