// E12-S06 PR 2 through the runtime on the fake GL: OHLC bars draw in exactly two instanced draws
// (the stem's 4-vertex strip, the ticks' 10-vertex strip; BQ-1, BQ-15); the gap seam adds one
// draw only while a `gap_before` bar is in view and the series is time-aligned (BQ-8, BQ-12);
// `dataState` posts on a change and an empty view hides the background layer (BQ-9); a pick
// that misses every object answers the bar under the point (`kind: "bar"`).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { encodeCandles, type FromWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { THEME } from "../layers/fixtures.js";

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
const states = (): string[] =>
  out.filter((m) => m.t === "dataState").map((m) => (m as { state: string }).state);

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

describe("OHLC bars (BQ-1, BQ-15)", () => {
  it("draw in exactly two instanced draws: the stem (4 vertices), the ticks (10)", () => {
    cmd({ k: "addSeries", series: 0, kind: "bars" });
    bars();
    view(0, 40); // ≈ 19 CSS px a bar
    frame();
    const cap = rt.series(1, 0)?.ring.capacity;
    expect(drawn(() => view(1, 41))).toEqual([`4 ${cap}`, `10 ${cap}`]);
    const batch = gl.uniforms.filter((u) => u[0] === "u_batch").slice(-2);
    expect(batch.map((u) => u[1])).toEqual([3, 2]); // CANDLE_PART.stem, .ticks
  });

  it("below 5 CSS px draw the candle mark: two 4-vertex draws, the wick and body parts", () => {
    cmd({ k: "addSeries", series: 0, kind: "bars" });
    bars();
    frame();
    const cap = rt.series(1, 0)?.ring.capacity;
    view(-200, 59); // ≈ 3 CSS px a bar
    frame();
    expect(drawn(() => view(-201, 58))).toEqual([`4 ${cap}`, `4 ${cap}`]);
    expect(
      gl.uniforms
        .filter((u) => u[0] === "u_batch")
        .slice(-2)
        .map((u) => u[1]),
    ).toEqual([0, 1]);
  });
});

describe("the gap seam (BQ-8, BQ-12)", () => {
  const flags = Uint8Array.from({ length: N }, (_, i) => (i === 30 ? 1 : 0));

  it("adds one draw only while the gap is in view", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    bars(flags);
    view(0, 40);
    frame();
    const cap = rt.series(1, 0)?.ring.capacity;
    expect(drawn(() => view(1, 41))).toEqual([`4 ${cap}`, `4 ${cap}`, "4 1"]);
    expect(drawn(() => view(35, 59))).toEqual([`4 ${cap}`, `4 ${cap}`]);
    expect(drawn(() => view(0, 20))).toEqual([`4 ${cap}`, `4 ${cap}`]);
  });

  it("never draws for a series that is not time-aligned; a bad option is ignored", () => {
    cmd({ k: "addSeries", series: 0, kind: "bars" });
    bars(flags);
    cmd({ k: "setSeriesOptions", series: 0, options: { isTimeAligned: false } });
    expect(drawn(() => view(0, 40))).toHaveLength(2);
    cmd({ k: "setSeriesOptions", series: 0, options: { isTimeAligned: "no" } });
    cmd({ k: "setSeriesOptions", series: 7, options: { isTimeAligned: true } });
    expect(drawn(() => view(1, 41))).toHaveLength(2);
    cmd({ k: "setSeriesOptions", series: 0, options: { isTimeAligned: true } });
    expect(drawn(() => view(0, 40))).toHaveLength(3);
  });
});

describe("a theme switch (AC 7)", () => {
  const flags = Uint8Array.from({ length: N }, (_, i) => (i === 30 ? 1 : 0));

  it("OHLC bars and the seam: palette uniforms only, no buffer write, colours re-read", () => {
    cmd({ k: "addSeries", series: 0, kind: "bars" });
    bars(flags);
    view(0, 40);
    frame();
    const writes = gl.writes.length;
    const before = gl.draws.length;
    const palettes = (): number[][] =>
      gl.uniforms.filter((u) => u[0] === "u_palette") as number[][];
    const seen = palettes().length;
    cmd({ k: "setTheme", theme: { ...THEME, "color.candle.up": "#00ff00" } });
    frame();
    expect(gl.writes.length - writes).toBe(0);
    expect(gl.draws.length - before).toBeGreaterThanOrEqual(3); // stem, ticks, seam still drawn
    const fresh = palettes().slice(seen);
    expect(fresh).toHaveLength(gl.draws.length - before); // every batch, the seam's too
    expect(fresh.every((u) => u.slice(1, 5).join() === "0,1,0,1")).toBe(true);
  });
});

describe("dataState (BQ-9)", () => {
  const background = (): boolean | undefined => rt.graph(1)?.get("main/background")?.visible;

  it("posts empty, then ready with bars in view, then empty again; the grid layer follows", () => {
    frame();
    expect([states(), background()]).toEqual([["empty"], false]);
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    bars();
    view(0, 40);
    frame();
    expect([states(), background()]).toEqual([["empty", "ready"], true]);
    view(1, 41);
    frame();
    expect(states()).toHaveLength(2); // edge-triggered: no repeat
    bars(undefined, 0, 0); // every bar gone
    frame();
    expect([states(), background()]).toEqual([["empty", "ready", "empty"], false]);
    bars();
    frame();
    expect([states().at(-1), background()]).toEqual(["ready", true]);
    cmd({ k: "removeSeries", series: 0 });
    frame();
    expect(states().at(-1)).toBe("empty");
  });
});

describe("bar picking", () => {
  const picks = (): FromWorker[] => out.filter((m) => m.t === "pick");

  it("a pick that misses every object answers the bar under the point", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles" });
    bars();
    view(0, 40);
    frame();
    for (let y = 0; y < 400; y += 2) cmd({ k: "pickAt", x: 300, y, reqId: y });
    const hits = picks().filter((p) => (p as { kind: string }).kind === "bar");
    expect(hits.length).toBeGreaterThan(0);
    const bar = (hits[0] as { bar: number }).bar;
    expect(hits.every((p) => (p as { objectId: string }).objectId === "series.0")).toBe(true);
    expect(hits.every((p) => (p as { bar: number }).bar === bar)).toBe(true);
    expect(picks().length - hits.length).toBeGreaterThan(0); // far above and below: none
  });

  it("a series on another pane has no bar to pick on pane 0", () => {
    cmd({ k: "addSeries", series: 0, kind: "candles", pane: 1 });
    bars();
    view(0, 40);
    frame();
    for (let y = 0; y < 400; y += 4) cmd({ k: "pickAt", x: 300, y });
    expect(picks().every((p) => (p as { kind: string }).kind !== "bar")).toBe(true);
  });
});
