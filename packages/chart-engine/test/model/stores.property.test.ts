// E11-T03 property tests, 10 000 seeded cases each (a mulberry32 loop, seed = base + case, printed
// on failure: fast-check is not in the lockfile, README BQ-30). For any series and any append /
// patch / prepend / replace sequence the store equals a plain-array model, timeToIndex(
// indexToTime(i)) === i, prepend yields the union of both inputs, and footprint offsets are
// non-decreasing with offsets[bars] === cellCount.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { BarStore, FootprintStore, ModelRejection } from "../../src/model/index.js";
import { bars, STEP, T0 } from "./fixtures.js";

describe("property: BarStore mutations match a plain-array model", () => {
  it("holds for 10 000 seeded cases", { timeout: 60_000 }, () => {
    const failures: string[] = [];
    const seen = { evicted: 0, wrapped: 0, rejected: 0 };
    for (let c = 0; c < 10_000 && failures.length === 0; c += 1) {
      const seed = 20261030 + c;
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const fail = (s: number, what: string): number =>
        failures.push(`seed=${seed} step ${s}: ${what}`);
      const maxBars = 4 + int(40);
      const store = new BarStore({ maxBars, initialCapacity: 1 + int(16) });
      let model: number[] = []; // logical minute per bar; ticks and times derive from it
      const bump = new Map<number, number>(); // minute → ticks a patch added to its OHLC
      let [lo, hi] = [0, 0]; // next prepend ends below lo; next append starts at hi
      for (let s = 0; s < 10; s += 1) {
        const op = int(4);
        const k = int(op === 3 ? maxBars + 1 : 8);
        const before = model.length;
        try {
          if (op === 0) {
            const r = store.append(bars(hi, k));
            model = [...model, ...Array.from({ length: k }, (_, i) => hi + i)];
            const shift = Math.max(0, model.length - maxBars);
            model = model.slice(shift);
            if (
              [r.from, r.to, r.indexShift].join() !== [before - shift, model.length, shift].join()
            )
              fail(s, "append range");
            seen.evicted += shift;
            hi += k;
          } else if (op === 1) {
            const r = store.prepend(bars(lo - k, k));
            model = [...Array.from({ length: k }, (_, i) => lo - k + i), ...model];
            if (r.indexShift !== k) fail(s, "prepend shift");
            lo -= k;
          } else if (op === 2 && before > 0) {
            const at = int(before);
            const n = Math.min(k, before - at);
            const [b, v] = [bars(model[at] ?? 0, n), 1 + int(50)];
            for (const col of [b.open, b.high, b.low, b.close])
              col.forEach((x, i) => (col[i] = x + v));
            store.patch(at, b);
            for (let i = 0; i < n; i += 1) bump.set((model[at] ?? 0) + i, v);
          } else if (op === 3) {
            store.replace(bars(hi, k));
            model = Array.from({ length: k }, (_, i) => hi + i);
            bump.clear();
            [lo, hi] = [hi, hi + k];
          }
        } catch (e) {
          if (!(e instanceof ModelRejection))
            throw new Error(`seed=${seed} step ${s}`, { cause: e });
          seen.rejected += 1;
          if (!((op === 0 && k > maxBars) || (op === 1 && before + k > maxBars))) {
            fail(s, `unexpected ${e.reason}`);
          }
        }
        if (store.ringHead + store.length > store.capacity) seen.wrapped += 1;
        for (let i = 0; i < model.length; i += 1) {
          const t = store.indexToTime(i); // on the ring as it stands, before view() linearises it
          if (t !== T0 + (model[i] ?? 0) * STEP) fail(s, `time ${i}`);
          if (store.timeToIndex(t) !== i) fail(s, `timeToIndex ${i}`);
        }
        const view = store.view();
        if (view.length !== model.length) fail(s, "length");
        for (let i = 0; i < model.length; i += 1) {
          const m = model[i] ?? 0;
          const v = bump.get(m) ?? 0;
          const want = [m + v, m + 3 + v, m - 2 + v, m + 1 + v, Math.abs(m % 97) + 1, (m % 7) - 3];
          const cols = [view.open, view.high, view.low, view.close, view.volume, view.delta];
          if (cols.some((col, j) => col[i] !== want[j])) fail(s, `ohlcv ${i}`);
        }
      }
    }
    expect(failures.slice(0, 5)).toEqual([]);
    expect([seen.evicted > 1_000, seen.wrapped > 1_000, seen.rejected > 100]).toEqual([
      true,
      true,
      true,
    ]);
  });
});

describe("property: footprint offsets are prefix sums of the cells", () => {
  it("holds for 10 000 seeded batches", { timeout: 60_000 }, () => {
    const failures: string[] = [];
    const store = new FootprintStore();
    for (let c = 0; c < 10_000; c += 1) {
      const seed = 20261031 + c;
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const counts = Array.from({ length: int(12) }, () => int(6));
      const offsets = new Uint32Array(counts.length + 1);
      for (let i = 0; i < counts.length; i += 1)
        offsets[i + 1] = (offsets[i] ?? 0) + (counts[i] ?? 0);
      const cells = offsets[counts.length] ?? 0;
      const price = Int32Array.from({ length: cells }, (_, i) => i * 2 - cells);
      store.replace({
        barIndexOffsets: offsets,
        cellPriceLevel: price,
        cellBidVol: new Float32Array(cells).fill(1),
        cellAskVol: new Float32Array(cells),
        cellTradeCount: new Uint16Array(cells),
        priceOrigin: 0,
        tickSize: 1,
      });
      const o = store.offsets;
      let ok = o[store.bars] === store.cellCount;
      for (let b = 0; b < store.bars; b += 1) {
        ok &&= (o[b + 1] ?? 0) >= (o[b] ?? 0) && store.cellsFor(b)?.priceLevel.length === counts[b];
        for (let i = o[b] ?? 0; i < (o[b + 1] ?? 0); i += 1) ok &&= store.barIndex[i] === b;
      }
      if (!ok) failures.push(`seed=${seed}`);
    }
    expect(failures.slice(0, 5)).toEqual([]);
  });
});
