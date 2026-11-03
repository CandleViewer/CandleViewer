// E12-S07 through the runtime on the fake GL: `setSeriesKind` (and the `heikinAshi` option)
// redraws a series as hollow candles, OHLC bars or Heikin-Ashi over the same store, with no data
// resent and the same two draws; Heikin-Ashi picks answer the store's bar (R-4); HA with a
// footprint is refused (`ENGINE_SERIES_INCOMPATIBLE`) and the series keeps drawing; the two
// metrics count the switch (to the end of its frame) and the refused combination.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  encodeCandles,
  ENGINE_SERIES_INCOMPATIBLE,
  type FromWorker,
} from "../../src/worker/protocol.js";
import {
  createRenderRuntime,
  type RenderRuntime,
  SWITCH_BUCKETS_MS,
} from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { ringBar, storeBar, THEME } from "../layers/fixtures.js";

let out: FromWorker[];
let rt: RenderRuntime;
let gl: FakeGl;
const frame = (ms = 16): void => void vi.advanceTimersByTime(ms);
const cmd = (c: object): void => rt.handle({ t: "command", id: 1, cmd: c });
const N = 60;
function bars(flags?: Uint8Array, series = 0, N = 60): void {
  const open = Int32Array.from({ length: N }, (_, i) => 100 + (i % 7));
  const { layout, buffer } = encodeCandles({
    time: Float64Array.from({ length: N }, (_, i) => i * 60e6),
    open,
    high: open.map((o) => o + 3),
    low: open.map((o) => o - 2),
    close: open.map((o, i) => o + ((i % 3) - 1)),
    volume: new Float32Array(N).fill(1),
    ...(flags && { flags }),
    priceOrigin: 0,
    tickSize: 1,
  });
  rt.handle({ t: "data", id: 1, store: "bars", op: "replace", layout, buffer, series });
}
const view = (from: number, to: number): void =>
  cmd({ k: "setViewport", timeStart: from * 60e6, timeEnd: to * 60e6 });
const drawn = (fn: () => void): string[] => {
  const before = gl.draws.length;
  fn();
  frame();
  return gl.draws.slice(before);
};
beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  gl = new FakeGl({ params: ROOMY });
  gl.trackDraws = true;
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    // Autoscale over the bars' ticks (the series is not an extent source until E12-S08).
    priceSources: [
      {
        kind: "series",
        version: 0,
        extent: (_i0: number, _i1: number, o: Float64Array) => ((o[0] = 95), (o[1] = 110), true),
        minLow: () => 95,
      },
    ],
  });
  const canvas = { width: 800, height: 400, getContext: () => gl };
  rt.handle({
    t: "init",
    id: 1,
    canvas,
    dpr: 1,
    theme: THEME,
    config: { bench: true, syncGroup: null },
  });
});

afterEach(() => {
  vi.useRealTimers();
});

const entry = () => {
  const s = rt.series(1, 0);
  if (s === undefined) throw new Error("no series 0");
  return s;
};
const labels = (): (string | undefined)[] => entry().candle.blocks.map((b) => b.label);
const errors = (): FromWorker[] => out.filter((m) => m.t === "error");
const acks = (): number => out.filter((m) => m.t === "ack").length;

function candles(): void {
  cmd({ k: "addSeries", series: 0, kind: "candles" });
  bars();
  view(0, 40); // ≈ 19 CSS px a bar
  frame();
}

describe("setSeriesKind: the same store, no data resent", () => {
  it("hollow: the hollow parts in the same two draws, the ring's bits set in place", () => {
    candles();
    const s = entry();
    const [data, sent, cap] = [s.ring.data, acks(), s.ring.capacity];
    const before = Array.from({ length: N }, (_, i) => storeBar(s.store, i));
    cmd({ k: "setSeriesKind", series: 0, kind: "hollow" });
    expect(drawn(() => view(1, 41))).toEqual([`4 ${cap}`, `4 ${cap}`]);
    const batch = gl.uniforms.filter((u) => u[0] === "u_batch").slice(-2);
    expect(batch.map((u) => u[1])).toEqual([5, 6]); // CANDLE_PART.hollowWick, .hollowBody
    expect([s.kind, s.ring.data, s.ring.hollow, acks()]).toEqual(["hollow", data, true, sent]);
    expect(labels()).toEqual(["series.hollow.wick", "series.hollow.body", "series.hollow.seam"]);
    expect(Array.from({ length: N }, (_, i) => storeBar(s.store, i))).toEqual(before);
  });

  it("OHLC and back to candles: the parts follow; addSeries hollow starts hollow", () => {
    candles();
    cmd({ k: "setSeriesKind", series: 0, kind: "bars" });
    frame();
    expect(entry().candle.blocks.map((b) => b.ints[0])).toEqual([3, 2, 4]);
    cmd({ k: "setSeriesKind", series: 0, kind: "candles" });
    frame();
    expect(entry().candle.blocks.map((b) => b.ints[0])).toEqual([0, 1, 4]);
    cmd({ k: "addSeries", series: 1, kind: "hollow" });
    bars(undefined, 1);
    frame();
    expect(rt.series(1, 1)?.candle.blocks.map((b) => b.ints[0])).toEqual([5, 6, 4]);
  });

  it("Heikin-Ashi: HA bars drawn, the store and the pick stay real (R-4)", () => {
    candles();
    const s = entry();
    cmd({ k: "setSeriesKind", series: 0, kind: "candles", heikinAshi: true });
    frame();
    expect(s.candle.heikinAshi).toBe(true);
    const o = (i: number): number => ringBar(s.ring, i)[0] ?? 0;
    const so = (i: number): number => storeBar(s.store, i)[0] ?? 0;
    expect(o(5)).not.toBe(so(5));
    expect(s.store.columns.open[s.store.ringHead + 5]).toBe(so(5));
    for (let y = 0; y < 400; y += 2) cmd({ k: "pickAt", x: 300, y });
    const hits = out.filter((m) => m.t === "pick" && (m as { kind: string }).kind === "bar");
    expect(hits.length).toBeGreaterThan(0);
    const bar = (hits[0] as { bar: number }).bar;
    expect(bar).toBeGreaterThanOrEqual(0);
    expect(bar).toBeLessThan(N);
    expect(hits.every((p) => (p as { objectId: string }).objectId === "series.0")).toBe(true);
    cmd({ k: "setSeriesKind", series: 0, kind: "candles" });
    frame();
    expect([s.ring.ha, ringBar(s.ring, 5)]).toEqual([null, storeBar(s.store, 5)]);
  });

  it("the `heikinAshi` series option is the same switch; a non-boolean is ignored", () => {
    candles();
    cmd({ k: "setSeriesOptions", series: 0, options: { heikinAshi: true } });
    frame();
    expect(entry().candle.heikinAshi).toBe(true);
    cmd({ k: "setSeriesOptions", series: 0, options: { heikinAshi: "yes" } });
    expect(entry().candle.heikinAshi).toBe(true);
    cmd({ k: "setSeriesOptions", series: 0, options: { heikinAshi: false } });
    expect(entry().candle.heikinAshi).toBe(false);
  });

  it("an unknown series is a recoverable error", () => {
    candles();
    cmd({ k: "setSeriesKind", series: 9, kind: "hollow" });
    expect(errors().at(-1)).toMatchObject({ code: "ENGINE_DECODE_ERROR", recoverable: true });
  });
});

describe("Heikin-Ashi with a footprint (refused)", () => {
  function footprint(): void {
    const { layout, buffer } = encodeCandles({
      time: Float64Array.of(0),
      open: Int32Array.of(1),
      high: Int32Array.of(1),
      low: Int32Array.of(1),
      close: Int32Array.of(1),
      volume: Float32Array.of(1),
      priceOrigin: 0,
      tickSize: 1,
    });
    rt.handle({ t: "data", id: 1, store: "footprint", op: "replace", layout, buffer });
  }

  it("posts ENGINE_SERIES_INCOMPATIBLE, counts it, and the series keeps drawing", () => {
    candles();
    footprint();
    const s = entry();
    const [written, cap] = [s.ring.written, s.ring.capacity];
    cmd({ k: "setSeriesKind", series: 0, kind: "hollow", heikinAshi: true });
    expect(errors().at(-1)).toMatchObject({
      t: "error",
      code: ENGINE_SERIES_INCOMPATIBLE,
      recoverable: true,
    });
    expect(drawn(() => view(1, 41))).toEqual([`4 ${cap}`, `4 ${cap}`]);
    expect([s.kind, s.candle.heikinAshi, s.ring.hollow, s.ring.written]).toEqual([
      "candles",
      false,
      false,
      written,
    ]);
    expect(labels()[0]).toBe("series.candle.wick");
    expect(rt.seriesMetrics(1)?.incompatible).toEqual({ "heikin-ashi+footprint": 1 });
    cmd({ k: "setSeriesOptions", series: 0, options: { heikinAshi: true } });
    expect(rt.seriesMetrics(1)?.incompatible).toEqual({ "heikin-ashi+footprint": 2 });
    cmd({ k: "setSeriesKind", series: 0, kind: "hollow" }); // no HA: allowed
    expect(entry().kind).toBe("hollow");
  });
});

describe("footprint data under Heikin-Ashi, and Heikin-Ashi over OHLC bars (refused)", () => {
  function footprintBatch(): void {
    const { layout, buffer } = encodeCandles({
      time: Float64Array.of(0),
      open: Int32Array.of(1),
      high: Int32Array.of(1),
      low: Int32Array.of(1),
      close: Int32Array.of(1),
      volume: Float32Array.of(1),
      priceOrigin: 0,
      tickSize: 1,
    });
    rt.handle({ t: "data", id: 1, store: "footprint", op: "replace", layout, buffer });
  }

  it("a footprint batch after HA is refused, counted and acked; the HA series keeps drawing", () => {
    candles();
    cmd({ k: "setSeriesKind", series: 0, kind: "candles", heikinAshi: true });
    frame();
    const s = entry();
    const [written, cap, sent] = [s.ring.written, s.ring.capacity, acks()];
    footprintBatch();
    expect(errors().at(-1)).toMatchObject({ code: ENGINE_SERIES_INCOMPATIBLE, recoverable: true });
    expect(acks()).toBe(sent + 1);
    expect(rt.seriesMetrics(1)?.incompatible).toEqual({ "heikin-ashi+footprint": 1 });
    expect(drawn(() => view(1, 41))).toEqual([`4 ${cap}`, `4 ${cap}`]);
    expect([s.candle.heikinAshi, s.ring.written]).toEqual([true, written]);
    // Nothing was stored, so HA off then on again is not refused.
    cmd({ k: "setSeriesKind", series: 0, kind: "candles" });
    cmd({ k: "setSeriesKind", series: 0, kind: "candles", heikinAshi: true });
    expect(entry().candle.heikinAshi).toBe(true);
    cmd({ k: "setSeriesKind", series: 0, kind: "candles" });
    footprintBatch(); // without HA: accepted
    expect(rt.seriesMetrics(1)?.incompatible).toEqual({ "heikin-ashi+footprint": 1 });
  });

  it("HA over OHLC bars is refused: the bars keep drawing, the option path too", () => {
    cmd({ k: "addSeries", series: 0, kind: "bars" });
    bars();
    view(0, 40);
    frame();
    const s = entry();
    const cap = s.ring.capacity;
    cmd({ k: "setSeriesKind", series: 0, kind: "bars", heikinAshi: true });
    expect(errors().at(-1)).toMatchObject({ code: ENGINE_SERIES_INCOMPATIBLE, recoverable: true });
    cmd({ k: "setSeriesOptions", series: 0, options: { heikinAshi: true } });
    expect(rt.seriesMetrics(1)?.incompatible).toEqual({ "heikin-ashi+bars": 2 });
    expect([s.kind, s.candle.heikinAshi]).toEqual(["bars", false]);
    expect(drawn(() => view(1, 41))).toEqual([`4 ${cap}`, `10 ${cap}`]);
    cmd({ k: "setSeriesKind", series: 0, kind: "candles", heikinAshi: true }); // candles: allowed
    expect([entry().kind, entry().candle.heikinAshi]).toEqual(["candles", true]);
  });
});

describe("series_type_switch_duration_ms{target}", () => {
  it("one count per switch, in its target's bucket, at the end of the next frame", () => {
    candles();
    cmd({ k: "setSeriesKind", series: 0, kind: "hollow" });
    expect(rt.seriesMetrics(1)?.pending).toBe("hollow");
    frame();
    cmd({ k: "setSeriesKind", series: 0, kind: "candles", heikinAshi: true });
    frame();
    const m = rt.seriesMetrics(1);
    const total = (t: string): number =>
      Array.from(m?.switchDurationMs[t] ?? []).reduce((a, b) => a + b, 0);
    expect([total("hollow"), total("candles+heikin-ashi"), m?.pending]).toEqual([1, 1, null]);
    expect(m?.switchDurationMs["hollow"]?.length).toBe(SWITCH_BUCKETS_MS.length);
  });
});
