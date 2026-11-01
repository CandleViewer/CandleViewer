// E11-S05 through the runtime: `setPriceScale` (BQ-124) is a projection change only, the `bars`
// params carry the price origin (BQ-115), autoscale and the guard run once per frame before the
// uniforms (BQ-116, BQ-120), and the `viewport` message reports the scale. Frames by hand.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { columnSource } from "../../src/viewport/index.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { INPUT, type FromWorker } from "../../src/worker/protocol.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap, rows } from "../interaction/fixtures.js";

type Viewport = Extract<FromWorker, { t: "viewport" }>;

let out: FromWorker[];
let rt: RenderRuntime;
let gl: FakeGl;
const cols = {
  low: new Int32Array(2000).map((_, i) => 100_000 + i),
  high: new Int32Array(2000).map((_, i) => 100_010 + i),
  close: new Int32Array(2000).map((_, i) => 100_005 + i),
  length: 2000,
};
const series = columnSource(() => cols);
const frame = (): void => void vi.advanceTimersByTime(16);
const viewports = (): Viewport[] => out.filter((m): m is Viewport => m.t === "viewport");
const scale = (fields: object): void =>
  rt.handle({ t: "command", id: 1, cmd: { k: "setPriceScale", pane: 0, ...fields } });
const bars = (params: number[]): void =>
  rt.handle({
    t: "data",
    id: 1,
    store: "bars",
    op: "replace",
    layout: { count: 0, columns: [], params },
    buffer: new ArrayBuffer(0),
  });

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  gl = new FakeGl({ params: ROOMY });
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: minuteMap(),
    priceSources: [series],
  });
  const canvas = { width: 1064, height: 624, getContext: () => gl };
  const config = { bench: true, syncGroup: null };
  rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config });
  frame();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the price scale through the runtime", () => {
  it("fits the visible bars, takes the price origin from the bars params and reports both", () => {
    const first = viewports().at(-1);
    expect(first).toMatchObject({ pane: 0, mode: "linear", autoScale: true, inverted: false });
    expect(first?.priceLow).toBeGreaterThan(99_000); // fitted to the bars, not [0, 1]
    expect(first?.logReason).toBe("no-price-origin");
    bars([0, 0.5]);
    frame();
    expect(viewports().at(-1)).toMatchObject({ logAvailable: true, logReason: null });
    scale({ mode: "indexed" });
    frame();
    expect(viewports().at(-1)?.anchorTick).toEqual(expect.any(Number));
  });

  it("Scenario: A scale change costs a projection change only", () => {
    bars([0, 0.5]);
    frame();
    const posted = out.length;
    const writes = gl.writes.length;
    scale({ mode: "log" });
    frame();
    const after = out.slice(posted);
    // No data request and no series buffer upload: a viewport report and a frame. E11-S06 (C-66):
    // the relabelled axes post `axes`, and only the axis grid's own ring is rewritten.
    expect(after.map((m) => m.t).sort()).toEqual(["axes", "frame", "viewport"]);
    const grid = gl.writes.slice(writes);
    expect(grid.length).toBeLessThanOrEqual(1);
    const bytes = after.find((m) => m.t === "frame");
    expect(bytes?.t === "frame" && bytes.uploadedBytes % 36).toBe(0); // whole line instances
    expect(viewports().at(-1)).toMatchObject({ mode: "log", requestedMode: "log" });
  });

  it("a log asked for before the first bars is drawn by the frame that brings the origin", () => {
    scale({ mode: "log" }); // PaneOptions.priceScale at addPane, before any bars (BQ-120)
    frame();
    expect(viewports().at(-1)).toMatchObject({ mode: "linear", requestedMode: "log" });
    bars([0, 0.5]);
    frame();
    expect(viewports().at(-1)).toMatchObject({
      mode: "log",
      requestedMode: "log",
      logReason: null,
    });
  });

  it("a non-positive low falls back to linear before the frame and keeps the request", () => {
    bars([0, 0.5]);
    frame(); // the guard clears "no-price-origin" on the frame
    scale({ mode: "log" });
    frame();
    cols.low[7] = -1;
    series.version += 1;
    rt.handle({ t: "command", id: 1, cmd: { k: "setLod", candles: 0, footprint: 0 } }); // a frame
    frame();
    expect(viewports().at(-1)).toMatchObject({
      mode: "linear",
      requestedMode: "log",
      logAvailable: false,
      logReason: "non-positive",
    });
    cols.low[7] = 100_007;
  });

  it("a price-axis drag locks, the viewport reports it, and auto: true restores the fit", () => {
    const fitted = viewports().at(-1);
    rt.handle({
      t: "input",
      id: 1,
      kind: "pointer",
      events: rows([INPUT.down, 1030, 200, 1, 0, 0], [INPUT.move, 1030, 100, 1, 0, 8]),
    });
    frame();
    expect(viewports().at(-1)?.autoScale).toBe(false);
    scale({ auto: true });
    frame();
    expect(viewports().at(-1)).toMatchObject({ autoScale: true, priceLow: fitted?.priceLow });
  });
});
