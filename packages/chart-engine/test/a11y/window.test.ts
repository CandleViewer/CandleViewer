// E11-S13 PR-1: the a11y window (E06-D03 D1, D7, D9) and its version-safe decoder. Properties
// over seeded mulberry32 cases (BQ-81: no fast-check); a failure prints its seed.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  A11Y_WINDOW_ROWS,
  type A11yBars,
  computeA11yWindow,
  copyA11yWindow,
  EMPTY_A11Y_WINDOW,
  type MutableA11yWindow,
  readA11yUpdate,
  sameCursorWindow,
  sameView,
} from "../../src/a11y/window.js";

const MIN = 60e6;
/** A sorted µs time column as the window reads it; `timeToIndex` is the last bar at or before. */
function bars(times: readonly number[]): A11yBars {
  return {
    length: times.length,
    indexToTime: (i) => times[i] ?? Number.NaN,
    timeToIndex: (t) => {
      let [lo, hi] = [0, times.length]; // first index whose time is > t
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if ((times[mid] ?? Infinity) <= t) lo = mid + 1;
        else hi = mid;
      }
      return lo - 1;
    },
  };
}
/** n bars one minute apart from 0, in closed form (the property loop allocates no columns). */
const grid = (n: number): A11yBars => ({
  length: n,
  indexToTime: (i) => (i >= 0 && i < n ? i * MIN : Number.NaN),
  timeToIndex: (t) => Math.max(-1, Math.min(n - 1, Math.floor(t / MIN))),
});
const regular = (n: number, from = 0): number[] =>
  Array.from({ length: n }, (_, i) => from + i * MIN);
const view = { leftIndex: 0, barSpacing: 6, plotWidth: 600, dpr: 1 };
const L0 = { candles: 0, footprint: 0 };
const run = (b: A11yBars, t = Number.NaN, v = view, lod = L0, rows?: number): MutableA11yWindow =>
  computeA11yWindow({ ...EMPTY_A11Y_WINDOW }, b, v, t, lod, rows);

describe("computeA11yWindow", () => {
  it("is empty with no bars", () => {
    expect(run(bars([]))).toEqual(EMPTY_A11Y_WINDOW);
  });

  it("follows the latest bar and centres a 60-row window clamped at the end", () => {
    const w = run(bars(regular(1000)));
    expect([w.cursorBar, w.cursorTime, w.firstBar, w.lastBar]).toEqual([999, 999 * MIN, 940, 999]);
    expect([w.viewFirstBar, w.viewLastBar]).toEqual([0, 99]);
  });

  it("resolves a cursor in a gap to the bar before it and one before the data to bar 0", () => {
    const gappy = bars([0, MIN, 10 * MIN, 11 * MIN, 50 * MIN]);
    expect(run(gappy, 5 * MIN).cursorBar).toBe(1);
    expect(run(gappy, 30 * MIN).cursorBar).toBe(3);
    expect(run(gappy, -MIN)).toMatchObject({ cursorBar: 0, cursorTime: -MIN, firstBar: 0 });
  });

  it("keeps the cursor's time across prependHistory: its bar moves by the pages' length", () => {
    const t = 300 * MIN;
    const before = run(bars(regular(1000)), t);
    const after = run(bars(regular(1500, -500 * MIN)), t);
    expect(after.cursorTime).toBe(before.cursorTime);
    expect(after.cursorBar - before.cursorBar).toBe(500);
  });

  it("reports the tiers and N bars per device-px column at candle L2 only", () => {
    const thin = { ...view, barSpacing: 0.25, dpr: 2 };
    expect(run(bars(regular(9)), Number.NaN, thin, { candles: 2, footprint: 3 })).toMatchObject({
      candleTier: "L2",
      footprintTier: "L3",
      barsPerColumn: 2,
    });
    expect(
      run(bars(regular(9)), Number.NaN, thin, { candles: 1, footprint: 1 }).barsPerColumn,
    ).toBe(1);
  });

  it("holds its bounds over 10 000 seeded cases (any length, rows, cursor and view)", () => {
    for (let c = 0; c < 10_000; c += 1) {
      const rng = mulberry32(520_000 + c);
      const n = 1 + Math.floor(rng() * 3000);
      const rows = [0, Number.NaN, 1, A11Y_WINDOW_ROWS, 200, 5000][Math.floor(rng() * 6)];
      const t = rng() < 0.2 ? Number.NaN : (rng() * 1.4 - 0.2) * n * MIN;
      const v = {
        leftIndex: (rng() - 0.5) * 2 * n,
        barSpacing: 0.05 + rng() * 50,
        plotWidth: rng() * 3000,
        dpr: 1,
      };
      const w = run(grid(n), t, v, L0, rows);
      const size = Math.min(n, Math.max(1, Math.min(200, Math.floor(rows ?? 0) || 1)));
      const ok =
        w.firstBar >= 0 &&
        w.lastBar < n &&
        w.lastBar - w.firstBar + 1 === size &&
        w.cursorBar >= w.firstBar &&
        w.cursorBar <= w.lastBar &&
        (Number.isNaN(t)
          ? w.cursorBar === n - 1
          : w.cursorBar === Math.min(n - 1, Math.max(0, Math.floor(t / MIN)))) &&
        (w.firstBar === 0 ||
          w.lastBar === n - 1 ||
          w.cursorBar - w.firstBar === Math.floor(size / 2)) &&
        (w.viewLastBar === -1 ||
          (w.viewFirstBar >= 0 && w.viewFirstBar <= w.viewLastBar && w.viewLastBar < n));
      if (!ok) throw new Error(`seed ${520_000 + c}: ${JSON.stringify(w)}`);
    }
  });
});

describe("readA11yUpdate (the main thread's version-safe decoder)", () => {
  const msg = {
    t: "a11y",
    id: 1,
    cursorSummary: "",
    ...run(bars(regular(100))),
    origin: "data",
    viewTimeStart: 0,
    viewTimeEnd: 99 * MIN,
  };

  it("accepts a worker message and returns its window, origin and view times", () => {
    const u = readA11yUpdate(msg);
    expect(u?.window).toEqual(run(bars(regular(100))));
    expect([u?.origin, u?.viewTimeStart, u?.viewTimeEnd]).toEqual(["data", 0, 99 * MIN]);
  });

  it("accepts the empty window (0, -1) with no cursor", () => {
    const empty = { ...msg, firstBar: 0, lastBar: -1, cursorBar: -1 };
    expect(readA11yUpdate({ ...empty, viewFirstBar: 0, viewLastBar: -1 })?.window).toMatchObject({
      firstBar: 0,
      lastBar: -1,
      cursorBar: -1,
    });
  });

  it.each([
    ["an older worker's summary-only message", { t: "a11y", id: 1, cursorSummary: "x" }],
    ["a non-object", null],
    ["an unknown tier", { ...msg, candleTier: "L3" }],
    ["a cursor outside its window", { ...msg, cursorBar: msg.firstBar - 1 }],
    ["a window over the 200-row cap", { ...msg, firstBar: 0, lastBar: 200, cursorBar: 0 }],
    ["a fractional bar", { ...msg, viewFirstBar: 0.5 }],
    ["an inverted visible range", { ...msg, viewFirstBar: 10, viewLastBar: 5 }],
    ["an inverted empty window", { ...msg, firstBar: 5, lastBar: -1, cursorBar: -1 }],
    ["an inverted empty visible range", { ...msg, viewFirstBar: 5, viewLastBar: -1 }],
    ["an unknown origin", { ...msg, origin: "hover" }],
    ["no view times", { ...msg, viewTimeEnd: undefined }],
  ])("rejects %s", (_, bad) => {
    expect(readA11yUpdate(bad)).toBeNull();
  });
});

describe("copyA11yWindow and the edge-trigger comparisons", () => {
  const a = run(bars(regular(500)));
  it("a copy is the same cursor window and the same view", () => {
    const b: MutableA11yWindow = { ...EMPTY_A11Y_WINDOW };
    copyA11yWindow(b, a);
    expect(b).toEqual(a);
    expect([sameCursorWindow(a, b), sameView(a, b)]).toEqual([true, true]);
  });

  it.each([
    ["firstBar", { firstBar: a.firstBar + 1 }],
    ["cursorBar", { cursorBar: a.cursorBar - 1 }],
    ["candleTier", { candleTier: "L2" as const }],
    ["barsPerColumn", { barsPerColumn: 3 }],
    ["cursorTime", { cursorTime: Number.NaN }],
  ])("a changed %s is a different cursor window", (_, delta) => {
    expect(sameCursorWindow(a, { ...a, ...delta })).toBe(false);
  });

  it("a moved visible range is a different view only", () => {
    const moved = { ...a, viewFirstBar: a.viewFirstBar + 1 };
    expect([sameCursorWindow(a, moved), sameView(a, moved)]).toEqual([true, false]);
  });
});
