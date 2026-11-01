// E12-S06 through the runtime: `addSeries` gives a series its own BarStore and CandleRing; a
// `bars` batch with that series id is decoded (F-01), stored (F-02, append-merge, patch by
// time) and mirrored; the main series is the viewport's time map (G-8) and rebases the
// ObjectIndex (G-23). A refusal posts a recoverable ENGINE_DECODE_ERROR, counts
// `engine.data.rejected{reason}`, still acks, and leaves the store byte-identical.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ObjectIndex } from "../../src/hit/index.js";
import { CANDLE_DIR, type CandleRing } from "../../src/layers/index.js";
import {
  encodeCandles,
  ENGINE_DECODE_ERROR,
  type CandleColumns,
  type DataOp,
  type FromWorker,
} from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { ringBar, THEME } from "../layers/fixtures.js";
import type { BarStore } from "../../src/model/index.js";
import { snapshot } from "../model/fixtures.js";

const T0 = 1_700_000_000_000_000;
const MIN = 60e6;
let out: FromWorker[];
let rt: RenderRuntime;

/** `n` bars from minute `m`: open m, high m + 3, low m - 2, close m + 1. */
const candles = (m: number, n: number, extra: Partial<CandleColumns> = {}): CandleColumns => ({
  time: Float64Array.from({ length: n }, (_, i) => T0 + (m + i) * MIN),
  open: Int32Array.from({ length: n }, (_, i) => m + i),
  high: Int32Array.from({ length: n }, (_, i) => m + i + 3),
  low: Int32Array.from({ length: n }, (_, i) => m + i - 2),
  close: Int32Array.from({ length: n }, (_, i) => m + i + 1),
  volume: new Float32Array(n).fill(1),
  priceOrigin: 50_000,
  tickSize: 0.1,
  ...extra,
});
const cmd = (c: object): void => rt.handle({ t: "command", id: 1, cmd: c });
const send = (series: number | undefined, op: DataOp, d: CandleColumns): void => {
  const { layout, buffer } = encodeCandles(d);
  rt.handle({ t: "data", id: 1, store: "bars", op, layout, buffer, series });
};
const errors = (): string[] =>
  out.flatMap((m) => (m.t === "error" && m.code === ENGINE_DECODE_ERROR ? [m.message] : []));
const acks = (): number => out.filter((m) => m.t === "ack").length;
/** The series' store; every caller has added it, so absence is a failure, not undefined. */
const store = (sid = 0): BarStore => {
  const s = rt.series(1, sid)?.store;
  if (s === undefined) throw new Error(`no series ${sid}`);
  return s;
};

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
  });
  const canvas = { width: 1064, height: 624, getContext: () => new FakeGl({ params: ROOMY }) };
  rt.handle({
    t: "init",
    id: 1,
    canvas,
    dpr: 1,
    theme: THEME,
    config: { bench: true, syncGroup: null },
  });
  vi.advanceTimersByTime(16);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("addSeries / removeSeries", () => {
  it("a series owns a store and a ring; the first on pane 0 is the time map (G-8)", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    cmd({ k: "addSeries", series: 7, kind: "bars" });
    send(0, "replace", candles(0, 30));
    send(7, "replace", candles(0, 5));
    const main = rt.series(1, 0);
    expect([main?.kind, main?.pane, main?.store.length, main?.ring.length]).toEqual([
      "candles",
      0,
      30,
      30,
    ]);
    expect([rt.series(1, 7)?.kind, rt.series(1, 7)?.store.length]).toEqual(["bars", 5]);
    vi.advanceTimersByTime(16);
    const view = out.filter((m) => m.t === "viewport").at(-1);
    expect(view).toMatchObject({ timeEnd: expect.any(Number) });
    // The time range now comes from the store: the last bar's time is inside the window.
    const last = T0 + 29 * MIN;
    expect((view as { timeStart: number }).timeStart).toBeLessThanOrEqual(last);
    expect(acks()).toBe(2);
  });

  it("refuses a duplicate id and an unknown removal, recoverably", () => {
    cmd({ k: "addSeries", series: 1, kind: "candles" });
    cmd({ k: "addSeries", series: 1, kind: "bars" });
    cmd({ k: "removeSeries", series: 9 });
    expect(errors()).toEqual(["series 1 already exists on chart 1", "no series 9 on chart 1"]);
    expect(rt.series(1, 1)?.kind).toBe("candles");
  });

  it("removing the main series drops its store and rebuilds the object index", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    send(0, "replace", candles(0, 10));
    const spy = vi.spyOn(rt.pickIndex(1)?.objects as ObjectIndex, "onMutation");
    cmd({ k: "removeSeries", series: 0 });
    expect([rt.series(1, 0), spy.mock.calls.map(([r]) => r.op)]).toEqual([undefined, ["replace"]]);
    send(0, "append", candles(10, 1));
    expect(errors()).toEqual(["chart-engine: no series 0 on chart 1"]);
    expect(rt.dataRejected(1)).toEqual({ decode: 1 });
  });

  it("a series off pane 0 is never the main series", () => {
    cmd({ k: "addSeries", series: 3, kind: "candles", pane: 1 });
    cmd({ k: "addSeries", series: 4, kind: "candles" });
    send(4, "replace", candles(0, 3));
    const spy = vi.spyOn(rt.pickIndex(1)?.objects as ObjectIndex, "onMutation");
    send(3, "replace", candles(0, 2)); // not main: the object index is untouched
    expect([spy.mock.calls.length, rt.series(1, 3)?.store.length]).toEqual([0, 2]);
  });
});

describe("the series data path", () => {
  beforeEach(() => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    send(0, "replace", candles(0, 10));
  });

  it("append-merge: an equal first time patches the live bar, the rest append", () => {
    send(0, "append", candles(9, 1, { close: Int32Array.of(7), low: Int32Array.of(5) }));
    expect([store().length, store().view().close[9]]).toEqual([10, 7]);
    const ring = rt.series(1, 0)?.ring;
    expect(ringBar(ring as CandleRing, 9)).toEqual([9, 12, 5, 7, CANDLE_DIR.down << 4]);
    send(0, "append", candles(9, 3));
    expect(Array.from(store().view().open ?? [])).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    expect(errors()).toEqual([]);
  });

  it("patch names its bar by time; prepend pages history in front", () => {
    send(0, "patch", candles(4, 1, { high: Int32Array.of(40), close: Int32Array.of(40) }));
    send(0, "prepend", candles(-3, 3));
    expect([store().length, store().view().close[7], store().view().open[0]]).toEqual([13, 40, -3]);
    send(0, "patch", candles(50, 1)); // a time the series does not hold
    expect(errors()).toEqual(["chart-engine: patch names a bar time the series does not hold"]);
    expect(rt.dataRejected(1)).toEqual({ range: 1 });
  });

  it("a prepend rebases the object index's anchors (G-23)", () => {
    const objects = rt.pickIndex(1)?.objects as ObjectIndex;
    const spy = vi.spyOn(objects, "onMutation");
    send(0, "prepend", candles(-2, 2));
    expect(spy).toHaveBeenCalledTimes(1);
    expect({ ...spy.mock.calls[0]?.[0] }).toEqual({
      op: "prepend",
      from: 0,
      to: 2,
      indexShift: 2,
    });
  });

  it.each([
    [
      "F-02 high < low",
      candles(10, 1, { high: Int32Array.of(1), low: Int32Array.of(5) }),
      "relation",
    ],
    ["F-02 close above high", candles(10, 1, { close: Int32Array.of(99) }), "relation"],
    ["F-02 negative volume", candles(10, 1, { volume: Float32Array.of(-1) }), "negative"],
    ["a reserved flag bit", candles(10, 1, { flags: Uint8Array.of(0x80) }), "flags"],
    ["out of order", candles(3, 1), "order"],
    ["another frame", candles(10, 1, { tickSize: 0.5 }), "origin"],
  ])("refuses %s: decode error, counter, ack, the store byte-identical", (_, d, reason) => {
    const before = snapshot(store());
    const ring = rt.series(1, 0)?.ring;
    const ints = Array.from(ring?.ints ?? []);
    const acked = acks();
    send(0, "append", d);
    expect(errors()).toHaveLength(1);
    expect(rt.dataRejected(1)).toEqual({ [reason]: 1 });
    expect(acks()).toBe(acked + 1);
    expect(snapshot(store())).toBe(before);
    expect(Array.from(ring?.ints ?? [])).toEqual(ints);
  });

  it("a malformed bars layout is an F-01 decode refusal", () => {
    const { layout, buffer } = encodeCandles(candles(10, 1));
    const params = [50_000, 0];
    rt.handle({
      t: "data",
      id: 1,
      store: "bars",
      op: "append",
      layout: { ...layout, params },
      buffer,
      series: 0,
    });
    expect(errors()).toEqual(["chart-engine: priceOrigin / tickSize must be finite, tickSize > 0"]);
    expect(rt.dataRejected(1)).toEqual({ decode: 1 });
    expect(store().length).toBe(10);
  });

  it("a batch without a series id keeps the pre-E12-S06 path: no store is touched", () => {
    send(undefined, "append", candles(10, 4));
    expect([store().length, acks()]).toEqual([10, 2]);
  });

  it("an unexpected failure is not swallowed as a decode refusal", () => {
    const ring = rt.series(1, 0)?.ring as CandleRing;
    vi.spyOn(ring, "sync").mockImplementation(() => {
      throw new TypeError("bug");
    });
    send(0, "append", candles(10, 1));
    expect(
      out.filter((m) => m.t === "error").map((m) => (m as { message: string }).message),
    ).toEqual(["bug"]);
    expect(rt.dataRejected(1)).toEqual({});
  });
});

describe("the degraded-2d re-init keeps the DataModel (BQ-53)", () => {
  it("series, stores, rings and the main time map survive a second init", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    send(0, "replace", candles(0, 12));
    const before = rt.series(1, 0);
    const canvas = { width: 800, height: 400, getContext: () => null };
    rt.handle({
      t: "init",
      id: 1,
      canvas,
      dpr: 1,
      theme: THEME,
      config: { bench: true, syncGroup: null },
      profile: "degraded-2d",
    });
    expect(rt.series(1, 0)).toBe(before);
    send(0, "append", candles(12, 1));
    expect([store().length, before?.ring.length]).toEqual([13, 13]);
  });
});
