// E11-T03 BarStore: the ticket's Gherkin scenarios by name, then the unit matrix.
import { describe, expect, it } from "vitest";
import { BAR_BYTES, BarStore, ModelRejection } from "../../src/model/index.js";
import { ENGINE_DECODE_ERROR } from "../../src/worker/protocol.js";
import { bars, snapshot, STEP, T0 } from "./fixtures.js";

const rejectionOf = (fn: () => unknown): ModelRejection => {
  try {
    fn();
  } catch (e) {
    if (e instanceof ModelRejection) return e;
    throw e;
  }
  throw new Error("expected a rejection");
};

describe("Scenario: Appending a bar touches only the new range", () => {
  it("returns {100000, 100001}, writes no held bar and does not reallocate", () => {
    const store = new BarStore();
    store.append(bars(0, 100_000));
    const [cols, reallocs] = [store.columns, store.counters.reallocations];
    const held = Buffer.from(cols.close.buffer.slice(0, 100_000 * 4)).toString("base64");
    const range = store.append(bars(100_000, 1));
    expect({ ...range }).toEqual({ op: "append", from: 100_000, to: 100_001, indexShift: 0 });
    expect(store.columns).toBe(cols);
    expect(store.counters.reallocations).toBe(reallocs);
    expect(Buffer.from(cols.close.buffer.slice(0, 100_000 * 4)).toString("base64")).toBe(held);
  });
});

describe("Scenario: Prepending history preserves on-screen anchors", () => {
  it("shifts by 2000 and the anchor at 120 / T resolves to 2120, same time and price", () => {
    const store = new BarStore();
    store.append(bars(0, 5_000));
    const T = store.indexToTime(120);
    const price = store.view().close[120];
    const range = store.prepend(bars(-2_000, 2_000));
    expect({ ...range }).toEqual({ op: "prepend", from: 0, to: 2_000, indexShift: 2_000 });
    expect(store.timeToIndex(T)).toBe(2_120);
    expect([store.indexToTime(2_120), store.view().close[2_120]]).toEqual([T, price]);
  });
});

describe("Scenario: Hostile values are rejected at the store boundary", () => {
  it("NaN in close and Infinity in volume: ENGINE_DECODE_ERROR, byte-identical, counted", () => {
    // An Int32Array cannot hold NaN, so a NaN close arrives as a hostile untyped column: `type`.
    const store = new BarStore({ initialCapacity: 16 });
    store.append(bars(0, 10));
    const before = snapshot(store);
    const hostile = {
      ...bars(10, 2),
      close: Float64Array.of(Number.NaN, 1) as unknown as Int32Array,
    };
    hostile.volume[1] = Infinity;
    const err = rejectionOf(() => store.append(hostile));
    expect([err.code, err.reason]).toEqual([ENGINE_DECODE_ERROR, "type"]);
    const inf = rejectionOf(() => store.append({ ...bars(10, 2), volume: hostile.volume }));
    expect([inf.code, inf.reason]).toEqual([ENGINE_DECODE_ERROR, "non_finite"]);
    expect(snapshot(store)).toBe(before);
    expect(store.counters.rejectedMutations).toMatchObject({ type: 1, non_finite: 1 });
  });
});

describe("Scenario: The bar ceiling evicts instead of growing without bound", () => {
  it("a full 200 000-bar store takes 1 000 more: still 200 000, indexShift 1000", () => {
    const store = new BarStore({ maxBars: 200_000 });
    store.append(bars(0, 200_000));
    const cap = store.capacity;
    const range = store.append(bars(200_000, 1_000));
    expect({ ...range }).toEqual({ op: "append", from: 199_000, to: 200_000, indexShift: 1_000 });
    expect([store.length, store.capacity, store.counters.evictions]).toEqual([200_000, cap, 1_000]);
    expect(store.indexToTime(0)).toBe(T0 + 1_000 * STEP);
  });

  it("a catch-up batch larger than the spare room at the ceiling evicts without reallocating", () => {
    const store = new BarStore({ maxBars: 1_600 }); // ceiling capacity 2048: 448 spare slots
    store.append(bars(0, 1_600));
    const [cap, reallocs] = [store.capacity, store.counters.reallocations];
    store.append(bars(1_600, 1_000)); // 1000 > the 448 spare: evicts, never a same-size copy
    store.append(bars(2_600, 1_000));
    expect([cap, store.capacity, store.counters.reallocations]).toEqual([2_048, cap, reallocs]);
    expect([store.length, store.indexToTime(0)]).toEqual([1_600, T0 + 2_000 * STEP]);
  });
});

describe("BarStore ring, growth and index maps", () => {
  it("doubles capacity and re-linearises once", () => {
    const store = new BarStore({ initialCapacity: 4 });
    store.append(bars(0, 3));
    store.append(bars(3, 2));
    expect([store.capacity, store.counters.reallocations]).toEqual([8, 1]);
    expect(Array.from(store.view().open)).toEqual([0, 1, 2, 3, 4]);
  });

  it("wraps at the capacity boundary; view() linearises a wrapped ring once", () => {
    const store = new BarStore({ maxBars: 8, initialCapacity: 8 });
    store.append(bars(0, 8)); // at the ceiling: 8 + 8 / 4 spare → 16 slots
    for (const m of [8, 11, 14]) store.append(bars(m, 3)); // head 13: slots 13-15 then 0-4
    expect([store.ringHead, store.length, store.counters.reallocations]).toEqual([13, 8, 1]);
    expect(Array.from(store.view().open)).toEqual([9, 10, 11, 12, 13, 14, 15, 16]);
    expect([store.ringHead, store.counters.reallocations]).toEqual([4, 2]);
    const view = store.view();
    expect([store.view() === view, store.view().time === view.time]).toEqual([true, true]);
    const time = view.time;
    store.patch(7, { ...bars(16, 1), high: Int32Array.of(99), close: Int32Array.of(99) });
    expect([store.view().time === time, view.close[7]]).toEqual([true, 99]); // a patch: same arrays
    store.append(bars(17, 1));
    expect(store.view().time === time).toBe(false); // an append rebuilds the views
  });

  it("a power-of-two maxBars keeps spare slots: view() after each eviction rarely copies", () => {
    const store = new BarStore({ maxBars: 1_024 });
    store.append(bars(0, 1_024));
    const [spare, base] = [store.capacity - 1_024, store.counters.reallocations];
    for (let m = 1_024; m < 3_024; m += 1) {
      store.append(bars(m, 1));
      store.view();
    }
    expect(spare).toBeGreaterThanOrEqual(256);
    const copies = store.counters.reallocations - base;
    expect(copies).toBeLessThanOrEqual(Math.ceil(2_000 / (spare >> 1))); // centred: half each side
  });

  it("prepends into the ring's free front without reallocating, else reallocates", () => {
    const store = new BarStore({ initialCapacity: 8 });
    store.append(bars(0, 4));
    expect({ ...store.prepend(bars(-2, 2)) }).toEqual({
      op: "prepend",
      from: 0,
      to: 2,
      indexShift: 2,
    });
    expect(store.counters.reallocations).toBe(0);
    store.prepend(bars(-7, 5));
    expect([store.capacity, store.counters.reallocations]).toEqual([16, 1]);
    expect(Array.from(store.view().open)).toEqual([-7, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3]);
  });

  it("patches in place and returns the patched range", () => {
    const store = new BarStore();
    store.append(bars(0, 5));
    const patch = { ...bars(3, 2), high: Int32Array.of(70, 80), close: Int32Array.of(70, 80) };
    expect({ ...store.patch(3, patch) }).toEqual({ op: "patch", from: 3, to: 5, indexShift: 0 });
    expect(Array.from(store.view().close)).toEqual([1, 2, 3, 70, 80]);
  });

  it("timeToIndex: exact, between, before, after, empty and NaN", () => {
    const store = new BarStore();
    expect(store.timeToIndex(T0)).toBe(-1);
    store.append(bars(0, 10));
    const at = (m: number): number => store.timeToIndex(T0 + m * STEP);
    expect([at(4), at(4.5), at(-1), at(99), store.timeToIndex(Number.NaN)]).toEqual([
      4, 4, -1, 9, -1,
    ]);
    expect([store.indexToTime(10), store.indexToTime(-1), store.indexToTime(1.5)]).toEqual([
      Number.NaN,
      Number.NaN,
      Number.NaN,
    ]);
  });

  it("replace keeps the previous view drawable (no blank flash), then serves the new series", () => {
    const store = new BarStore();
    store.append(bars(0, 50));
    const old = store.view().close;
    const range = store.replace(bars(1_000, 3, 60_000, 0.5));
    expect({ ...range }).toEqual({ op: "replace", from: 0, to: 3, indexShift: 0 });
    expect([old.length, old[49]]).toEqual([50, 50]);
    expect([store.view().close[0], store.priceOrigin, store.tickSize]).toEqual([
      1_001, 60_000, 0.5,
    ]);
    expect(store.bytes).toBe(store.capacity * BAR_BYTES); // 33 since the flags column (E12-S06)
  });
});

describe("BarStore rejection matrix: refused whole, counted, store byte-identical", () => {
  const shorter = { ...bars(10, 2), high: Int32Array.of(1) };
  const backwards = { ...bars(10, 2), time: Float64Array.of(T0 + 11 * STEP, T0 + 10 * STEP) };
  const dup = Float64Array.of(T0 + 10 * STEP, T0 + 10 * STEP);
  const overInt = { ...bars(10, 1), open: Float64Array.of(2 ** 31) as unknown as Int32Array };
  const f64 = Float64Array.of(1e39) as unknown as Float32Array; // finite as f64, Infinity as f32
  const inf = Float32Array.of(Infinity);
  const cases: [string, string, (s: BarStore) => unknown][] = [
    ["length mismatch", "length", (s) => s.append(shorter)],
    ["time decreasing in the batch", "order", (s) => s.append(backwards)],
    ["append older than the last bar", "order", (s) => s.append(bars(5, 1))],
    ["append at the last bar's time", "order", (s) => s.append(bars(9, 2))],
    ["a repeated time in the batch", "order", (s) => s.append({ ...bars(10, 2), time: dup })],
    ["prepend newer than the first bar", "order", (s) => s.prepend(bars(1, 2))],
    ["prepend ending at the first bar's time", "order", (s) => s.prepend(bars(-1, 2))],
    ["patch outside the bars held", "range", (s) => s.patch(9, bars(9, 2))],
    ["patch before the previous bar", "order", (s) => s.patch(2, bars(0, 1))],
    ["patch after the next bar", "order", (s) => s.patch(2, bars(5, 1))],
    ["a different priceOrigin", "origin", (s) => s.append(bars(10, 1, 1))],
    ["a tick outside int32 (untyped)", "type", (s) => s.append(overInt)],
    ["1e39 in a Float64 volume", "type", (s) => s.append({ ...bars(10, 1), volume: f64 })],
    ["Infinity in a delta column", "non_finite", (s) => s.append({ ...bars(10, 1), delta: inf })],
    ["tickSize 0", "non_finite", (s) => s.append(bars(10, 1, 50_000, 0))],
    ["a declared count over maxBars", "ceiling", (s) => s.append(bars(10, 33))],
    ["prepend past maxBars", "ceiling", (s) => s.prepend(bars(-30, 30))],
    ["a hostile replace", "non_finite", (s) => s.replace({ ...bars(0, 1), priceOrigin: NaN })],
  ];
  it.each(cases)("%s", (_name, reason, mutate) => {
    const store = new BarStore({ maxBars: 32, initialCapacity: 16 });
    store.append(bars(0, 10));
    const before = snapshot(store);
    expect(rejectionOf(() => mutate(store)).reason).toBe(reason);
    expect(snapshot(store)).toBe(before);
    expect(store.counters.rejectedMutations[reason as "order"]).toBe(1);
  });

  it("an invalid maxBars is a programming error, not a rejection", () => {
    expect(() => new BarStore({ maxBars: 0 })).toThrow(RangeError);
    expect(() => new BarStore({ initialCapacity: Number.NaN })).toThrow(RangeError);
  });
});

describe("BarStore allocation discipline (26 §3.2 rule 4)", () => {
  it("1 000 mutations under a reader: ≤ 1 re-linearisation, same range and view objects", () => {
    const store = new BarStore({ initialCapacity: 4_096 });
    store.append(bars(0, 1_000));
    const [range, view] = [store.append(bars(1_000, 1)), store.view()];
    const [one, older, patch] = [bars(0, 1), bars(-1, 1), bars(0, 1)];
    let [next, prev] = [1_001, -1];
    for (let m = 0; m < 1_000; m += 1) {
      if (m % 3 === 0) {
        one.time[0] = T0 + next++ * STEP;
        expect(store.append(one)).toBe(range);
      } else if (m % 3 === 1) {
        older.time[0] = T0 + prev-- * STEP;
        expect(store.prepend(older)).toBe(range);
      } else {
        patch.time[0] = store.indexToTime(store.length - 1);
        expect(store.patch(store.length - 1, patch)).toBe(range);
      }
      expect(store.view()).toBe(view); // the first wrapped prepend re-linearises with front room
    }
    expect([store.counters.reallocations, store.counters.evictions]).toEqual([1, 0]);
  });
});
