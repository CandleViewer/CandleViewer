// E12-S06 BarStore additions: the optional `flags` column (BQ-3), the F-02 refusals (threat model
// CE-T04: high < low, open / close outside [low, high], negative volume, reserved flag bits),
// each leaving the store byte-identical, and append-merge (an equal first time patches the last
// bar).
import { describe, expect, it } from "vitest";
import { BAR_FLAG, BarStore, ModelRejection, type BarBatch } from "../../src/model/index.js";
import { ENGINE_DECODE_ERROR } from "../../src/worker/protocol.js";
import { bars, snapshot } from "./fixtures.js";

/** One bar at minute m with the given OHLC ticks, volume and flags. */
const bar = (m: number, ohlc: number[], volume = 1, flags?: number): BarBatch => ({
  ...bars(m, 1),
  open: Int32Array.of(ohlc[0] as number),
  high: Int32Array.of(ohlc[1] as number),
  low: Int32Array.of(ohlc[2] as number),
  close: Int32Array.of(ohlc[3] as number),
  volume: Float32Array.of(volume),
  ...(flags !== undefined && { flags: Uint8Array.of(flags) }),
});

describe("BarStore flags column (BQ-3)", () => {
  it("stores flags per bar, through the ring, and reads zeros where a batch has none", () => {
    const store = new BarStore({ initialCapacity: 2 });
    store.append(bars(0, 2));
    store.append({ ...bars(2, 2), flags: Uint8Array.of(BAR_FLAG.gapBefore, BAR_FLAG.forming) });
    store.prepend({ ...bars(-1, 1), flags: Uint8Array.of(BAR_FLAG.amended) });
    expect(Array.from(store.view().flags)).toEqual([8, 0, 0, 1, 2]);
    store.replace({ ...bars(10, 2), flags: Uint8Array.of(4, 0) });
    expect(Array.from(store.view().flags)).toEqual([4, 0]);
    store.replace(bars(20, 2));
    expect(Array.from(store.view().flags)).toEqual([0, 0]);
  });

  it("refuses a flags column of the wrong type or length", () => {
    const store = new BarStore();
    const wrongType = { ...bars(0, 1), flags: new Int8Array(1) as unknown as Uint8Array };
    expect(() => store.append(wrongType)).toThrow(ModelRejection);
    expect(() => store.append({ ...bars(0, 2), flags: new Uint8Array(1) })).toThrow(/length/);
    expect(store.counters.rejectedMutations).toMatchObject({ type: 1, length: 1 });
  });
});

describe("BarStore F-02: bars no candle can draw are refused, nothing written", () => {
  const cases: [string, BarBatch, string][] = [
    ["high < low", bar(9, [5, 4, 6, 5]), "relation"],
    ["open above high", bar(9, [9, 8, 2, 5]), "relation"],
    ["open below low", bar(9, [1, 8, 2, 5]), "relation"],
    ["close above high", bar(9, [5, 8, 2, 9]), "relation"],
    ["close below low", bar(9, [5, 8, 2, 1]), "relation"],
    ["negative volume", bar(9, [5, 8, 2, 6], -0.5), "negative"],
    ["a reserved flag bit", bar(9, [5, 8, 2, 6], 1, 0x10), "flags"],
  ];
  for (const [name, b, reason] of cases) {
    it(`refuses ${name} on every mutation and leaves the store byte-identical`, () => {
      const store = new BarStore({ initialCapacity: 16 });
      store.append(bars(0, 8));
      const before = snapshot(store);
      const at9 = { ...b, time: Float64Array.of(store.indexToTime(7)) };
      const muts: (() => unknown)[] = [
        () => store.append(b),
        () => store.append(at9, true),
        () => store.patch(7, at9),
        () => store.prepend({ ...b, time: Float64Array.of(store.indexToTime(0) - 1) }),
        () => store.replace(b),
      ];
      for (const m of muts) {
        let err: unknown = null;
        try {
          m();
        } catch (e) {
          err = e;
        }
        expect(err).toBeInstanceOf(ModelRejection);
        expect([(err as ModelRejection).code, (err as ModelRejection).reason]).toEqual([
          ENGINE_DECODE_ERROR,
          reason,
        ]);
      }
      expect(snapshot(store)).toBe(before);
      expect(store.counters.rejectedMutations[reason as "relation"]).toBe(muts.length);
    });
  }

  it("accepts the edges: doji, zero-range, open = high, close = low and zero volume", () => {
    const store = new BarStore();
    store.append(bar(0, [5, 8, 2, 5]));
    store.append(bar(1, [5, 5, 5, 5], 0));
    store.append(bar(2, [8, 8, 2, 2]));
    expect(store.length).toBe(3);
  });
});

describe("BarStore append-merge (equal time patches the last bar)", () => {
  it("a one-bar batch at the last bar's time is a patch of that bar", () => {
    const store = new BarStore();
    store.append(bars(0, 5));
    const r = store.append({ ...bar(4, [4, 9, 1, 8]) }, true);
    expect({ ...r }).toEqual({ op: "patch", from: 4, to: 5, indexShift: 0 });
    expect([store.length, store.view().close[4], store.view().high[4]]).toEqual([5, 8, 9]);
  });

  it("a longer batch patches the last bar and appends the rest, as one append range", () => {
    const store = new BarStore();
    store.append(bars(0, 5));
    const r = store.append(bars(4, 3), true);
    expect({ ...r }).toEqual({ op: "append", from: 4, to: 7, indexShift: 0 });
    expect(Array.from(store.view().open)).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });

  it("at maxBars the merged bar survives the eviction and the range rebases", () => {
    const store = new BarStore({ maxBars: 4, initialCapacity: 4 });
    store.append(bars(0, 4));
    const r = store.append(bars(3, 4), true); // patches minute 3, appends 4..6, evicts 0..2
    expect({ ...r }).toEqual({ op: "append", from: 0, to: 4, indexShift: 3 });
    expect(Array.from(store.view().open)).toEqual([3, 4, 5, 6]);
  });

  it("without merge an equal time is still refused, and an older one always is", () => {
    const store = new BarStore();
    store.append(bars(0, 3));
    const before = snapshot(store);
    expect(() => store.append(bars(2, 1))).toThrow(/not newer/);
    expect(() => store.append(bars(1, 1), true)).toThrow(/not newer/);
    expect(snapshot(store)).toBe(before);
  });

  it("merging into an empty store is a plain append", () => {
    const store = new BarStore();
    expect({ ...store.append(bars(0, 2), true) }).toMatchObject({ op: "append", from: 0, to: 2 });
    expect({ ...store.append(bars(2, 0), true) }).toMatchObject({ op: "append", from: 2, to: 2 });
  });
});
