// E12-S06 protocol additions: F-01's checked narrowing (`toTicks`, the frame check, the re-check
// at `encodeCandles` and at the worker's `decodeBars`), the 1-byte `flags` column, the
// `addSeries` / `removeSeries` commands and the optional `series` id on `data`.
import { describe, expect, it } from "vitest";
import {
  checkTickFrame,
  DecodeError,
  decodeBars,
  ENGINE_DECODE_ERROR,
  encodeCandles,
  rejectReason,
  TICK_WINDOW,
  toTicks,
  type CandleColumns,
} from "../../src/worker/protocol.js";

const candles = (n: number, flags = false): CandleColumns => ({
  time: Float64Array.from({ length: n }, (_, i) => 1_700_000_000_000_000 + i * 60e6),
  open: Int32Array.from({ length: n }, (_, i) => i),
  high: Int32Array.from({ length: n }, (_, i) => i + 3),
  low: Int32Array.from({ length: n }, (_, i) => i - 2),
  close: Int32Array.from({ length: n }, (_, i) => i + 1),
  volume: Float32Array.from({ length: n }, (_, i) => i + 0.5),
  flags: flags ? Uint8Array.from({ length: n }, (_, i) => i & 0x0f) : undefined,
  priceOrigin: 50_000,
  tickSize: 0.1,
});

describe("F-01 toTicks: checked narrowing, never truncation", () => {
  it("maps whole ticks from the frame's origin, decimal rounding included", () => {
    expect(toTicks(50_000.3, 50_000, 0.1)).toBe(3);
    expect(toTicks(49_999.9, 50_000, 0.1)).toBe(-1);
    expect(toTicks(50_000, 50_000, 0.1)).toBe(0);
    expect(Object.is(toTicks(50_000, 50_000, 0.1), -0)).toBe(false);
    expect(toTicks(0.00012, 0, 0.00001)).toBe(12);
    expect(toTicks(TICK_WINDOW, 0, 1)).toBe(TICK_WINDOW);
    expect(toTicks(-TICK_WINDOW, 0, 1)).toBe(-TICK_WINDOW);
  });

  it.each([
    ["a fractional tick", 50_000.35, 50_000, 0.1, /whole tick/],
    ["NaN", Number.NaN, 0, 1, /whole tick/],
    ["Infinity", Infinity, 0, 1, /whole tick/],
    ["above the window", TICK_WINDOW + 1, 0, 1, /int32 tick window/],
    ["below the window", -TICK_WINDOW - 1, 0, 1, /int32 tick window/],
    ["a zero tick size", 1, 0, 0, /tickSize > 0/],
    ["a negative tick size", 1, 0, -1, /tickSize > 0/],
    ["a non-finite origin", 1, Number.NaN, 1, /finite/],
    ["a window past float64", 1, 0, 1e300, /finite/],
  ])("refuses %s with ENGINE_DECODE_ERROR", (_, price, origin, tick, msg) => {
    let err: unknown = null;
    try {
      toTicks(price, origin, tick);
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(DecodeError);
    expect(err).toBeInstanceOf(RangeError);
    expect((err as DecodeError).code).toBe(ENGINE_DECODE_ERROR);
    expect((err as Error).message).toMatch(msg);
  });

  it("checkTickFrame accepts a sane frame", () => {
    expect(() => checkTickFrame(50_000, 0.1)).not.toThrow();
  });
});

describe("F-01 re-checked at encodeCandles", () => {
  it("refuses a tick outside the window, a bad frame and a non-int32 tick column", () => {
    const d = candles(3);
    expect(() => encodeCandles({ ...d, high: Int32Array.of(3, TICK_WINDOW + 1, 5) })).toThrow(
      /high\[1\] is outside/,
    );
    expect(() => encodeCandles({ ...d, low: Int32Array.of(0, -TICK_WINDOW - 1, 0) })).toThrow(
      DecodeError,
    );
    expect(() => encodeCandles({ ...d, tickSize: 0 })).toThrow(DecodeError);
    const floats = { ...d, open: new Float32Array(3) as unknown as Int32Array };
    expect(() => encodeCandles(floats)).toThrow(/Int32Array/);
    const wide = { ...d, flags: new Uint16Array(3) as unknown as Uint8Array };
    expect(() => encodeCandles(wide)).toThrow(/Uint8Array/);
  });

  it("sends flags as a seventh 1-byte column, and the batch decodes back", () => {
    const d = candles(5, true);
    const { layout, buffer } = encodeCandles(d);
    expect(layout.columns.map((c) => c.bytes)).toEqual([8, 4, 4, 4, 4, 4, 1]);
    expect(layout.params).toEqual([50_000, 0.1]);
    const back = decodeBars(layout, buffer);
    for (const k of ["time", "open", "high", "low", "close", "volume", "flags"] as const) {
      expect(Array.from(back[k] as ArrayLike<number>), k).toEqual(Array.from(d[k] ?? []));
    }
    expect([back.priceOrigin, back.tickSize]).toEqual([50_000, 0.1]);
  });

  it("decodes a six-column batch with no flags", () => {
    const { layout, buffer } = encodeCandles(candles(2));
    const back = decodeBars(layout, buffer);
    expect([back.flags, Array.from(back.close)]).toEqual([undefined, [1, 2]]);
  });
});

describe("decodeBars: the worker's half refuses what it cannot read", () => {
  const { layout, buffer } = encodeCandles(candles(2));
  it.each([
    ["a missing column", { ...layout, columns: layout.columns.slice(0, 5) }],
    [
      "a wrong width",
      { ...layout, columns: [{ offset: 0, bytes: 4 }, ...layout.columns.slice(1)] },
    ],
    ["no params", { ...layout, params: [] }],
    ["a bad frame", { ...layout, params: [0, -1] }],
  ] as const)("%s", (_, bad) => {
    expect(() => decodeBars(bad as never, buffer)).toThrow(DecodeError);
  });

  it("re-checks the tick window on the worker", () => {
    const d = candles(2);
    const enc = encodeCandles(d);
    new Int32Array(enc.buffer, enc.layout.columns[2]?.offset, 2)[1] = TICK_WINDOW + 7;
    expect(() => decodeBars(enc.layout, enc.buffer)).toThrow(/high\[1\]/);
  });
});

describe("series commands and the data series id (additive)", () => {
  const cmd = (c: object): unknown => ({ t: "command", id: 1, cmd: c });
  const data = (extra: object): unknown => {
    const { layout, buffer } = encodeCandles(candles(1));
    return { t: "data", id: 1, store: "bars", op: "append", layout, buffer, ...extra };
  };

  it("accepts addSeries, removeSeries and a series id on a bars batch", () => {
    expect(rejectReason(cmd({ k: "addSeries", series: 0, kind: "candles" }))).toBeNull();
    expect(rejectReason(cmd({ k: "addSeries", series: 3, kind: "bars", pane: 0 }))).toBeNull();
    expect(rejectReason(cmd({ k: "removeSeries", series: 3 }))).toBeNull();
    expect(rejectReason(data({ series: 2 }))).toBeNull();
    expect(rejectReason(data({}))).toBeNull();
  });

  it.each([
    { k: "addSeries", series: -1, kind: "candles" },
    { k: "addSeries", series: 1.5, kind: "candles" },
    { k: "addSeries", series: 1, kind: "line" },
    { k: "addSeries", series: 1, kind: "candles", pane: -2 },
    { k: "removeSeries" },
    { k: "removeSeries", series: "1" },
  ])("refuses a malformed series command %#", (c) => {
    expect(rejectReason(cmd(c))).toBe("malformed command");
  });

  it("refuses a bad series id, or a series id on another store", () => {
    expect(rejectReason(data({ series: -1 }))).toBe("bad series id");
    expect(rejectReason(data({ series: Number.NaN }))).toBe("bad series id");
    expect(rejectReason(data({ series: 1, store: "footprint" }))).toBe("a series batch is bars");
  });
});
