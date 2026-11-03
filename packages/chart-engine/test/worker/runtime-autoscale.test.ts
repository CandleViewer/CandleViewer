// E12-S11 PR A1 through the runtime: every series' `BarStore` is a price source of its pane (26
// §3.5, :390, the "autoscale wiring"), the main series first. Autoscale fits the real data with
// no injected `priceSources`; it fits the drawn candles (Heikin-Ashi included, refit on a kind
// switch); a removed series stops contributing; a degraded-2d re-init keeps the wiring.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  encodeCandles,
  type CandleColumns,
  type DataOp,
  type FromWorker,
} from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { THEME } from "../layers/fixtures.js";

type Viewport = Extract<FromWorker, { t: "viewport" }>;

const T0 = 1_700_000_000_000_000;
const MIN = 60e6;
let out: FromWorker[];
let rt: RenderRuntime;

/** `n` flat bars from minute `m` at tick `level`: low = open = level, high = close = level + 2. */
const flat = (m: number, n: number, level: number, origin = 50_000): CandleColumns => ({
  time: Float64Array.from({ length: n }, (_, i) => T0 + (m + i) * MIN),
  open: new Int32Array(n).fill(level),
  high: new Int32Array(n).fill(level + 2),
  low: new Int32Array(n).fill(level),
  close: new Int32Array(n).fill(level + 2),
  volume: new Float32Array(n).fill(1),
  priceOrigin: origin,
  tickSize: 0.1,
});
const join = (a: CandleColumns, b: CandleColumns): CandleColumns => {
  const cat = <T extends Int32Array | Float64Array | Float32Array>(x: T, y: T): T => {
    const r = new (x.constructor as new (n: number) => T)(x.length + y.length);
    r.set(x);
    r.set(y, x.length);
    return r;
  };
  return {
    ...a,
    time: cat(a.time, b.time),
    open: cat(a.open, b.open),
    high: cat(a.high, b.high),
    low: cat(a.low, b.low),
    close: cat(a.close, b.close),
    volume: cat(a.volume, b.volume),
  };
};
const cmd = (c: object): void => rt.handle({ t: "command", id: 1, cmd: c });
const send = (series: number, op: DataOp, d: CandleColumns): void => {
  const { layout, buffer } = encodeCandles(d);
  rt.handle({ t: "data", id: 1, store: "bars", op, layout, buffer, series });
};
const frame = (): void => void vi.advanceTimersByTime(16);
const priceWindow = (): [number, number] => {
  const v = out.filter((m): m is Viewport => m.t === "viewport").at(-1);
  return [v?.priceLow ?? Number.NaN, v?.priceHigh ?? Number.NaN];
};
const init = (): void => {
  const canvas = { width: 1064, height: 624, getContext: () => new FakeGl({ params: ROOMY }) };
  const config = { bench: true, syncGroup: null };
  rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme: THEME, config });
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
  init();
  frame();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Scenario: autoscale follows the series' own data", () => {
  it("fits the main series' extent and refits on a new snapshot", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    send(0, "replace", flat(0, 50, 1000));
    frame();
    const [lo, hi] = priceWindow();
    // [1000, 1002] with the 5 % margins: the window brackets the bars and nothing else.
    expect(lo).toBeLessThanOrEqual(1000);
    expect(lo).toBeGreaterThan(999);
    expect(hi).toBeGreaterThanOrEqual(1002);
    expect(hi).toBeLessThan(1003);
    send(0, "replace", flat(0, 50, 5000));
    frame();
    expect(priceWindow()[0]).toBeGreaterThan(4999);
    expect(priceWindow()[1]).toBeLessThan(5003);
  });

  it("a second series on the pane widens the window until it is removed", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    cmd({ k: "addSeries", series: 1, kind: "bars" });
    send(0, "replace", flat(0, 50, 1000));
    send(1, "replace", flat(0, 50, 3000));
    frame();
    expect(priceWindow()[1]).toBeGreaterThanOrEqual(3002);
    cmd({ k: "removeSeries", series: 1 });
    frame();
    expect(priceWindow()[1]).toBeLessThan(1003);
    expect(priceWindow()[0]).toBeGreaterThan(999);
  });

  it("a series in another price frame is converted into the pane's ticks", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    cmd({ k: "addSeries", series: 1, kind: "candles" });
    send(0, "replace", flat(0, 50, 1000)); // 50_000 + 0.1 × [1000, 1002]: 50_100 to 50_100.2
    send(1, "replace", flat(0, 50, 1000, 50_100)); // 50_200 to 50_200.2: ticks 2000 to 2002
    frame();
    expect(priceWindow()[1]).toBeGreaterThanOrEqual(2002);
    expect(priceWindow()[1]).toBeLessThan(2100);
  });

  it("fits the drawn Heikin-Ashi candles, refitting on the kind switch", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    // A gap from tick 0 to 1000 at bar 150: HA opens close it by halves, below the real lows.
    send(0, "replace", join(flat(0, 150, 0), flat(150, 50, 1000)));
    const from = T0 + 151 * MIN;
    cmd({ k: "setViewport", timeStart: from, timeEnd: from + 30 * MIN });
    frame();
    expect(priceWindow()[0]).toBeGreaterThan(999); // the real bars: [1000, 1002]
    cmd({ k: "setSeriesKind", series: 0, kind: "candles", heikinAshi: true });
    frame();
    expect(priceWindow()[0]).toBeLessThan(900); // the HA lows reach back toward the gap
    cmd({ k: "setSeriesKind", series: 0, kind: "candles" });
    frame();
    expect(priceWindow()[0]).toBeGreaterThan(999);
  });

  it("removing the main series leaves the window where it was, then a new one is fitted", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    send(0, "replace", flat(0, 50, 1000));
    frame();
    const held = priceWindow();
    cmd({ k: "removeSeries", series: 0 });
    frame();
    expect(priceWindow()).toEqual(held);
    cmd({ k: "addSeries", series: 2, kind: "candles" });
    send(2, "replace", flat(0, 50, 7000));
    frame();
    expect(priceWindow()[0]).toBeGreaterThan(6999);
  });

  it("a degraded-2d re-init keeps every series wired to the new viewport", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    send(0, "replace", flat(0, 50, 1000));
    frame();
    init(); // the handoff: a second init for the same chart keeps the DataModel (BQ-53)
    frame();
    send(0, "replace", flat(0, 50, 4000));
    frame();
    expect(priceWindow()[0]).toBeGreaterThan(3999);
    expect(priceWindow()[1]).toBeLessThan(4003);
  });
});
