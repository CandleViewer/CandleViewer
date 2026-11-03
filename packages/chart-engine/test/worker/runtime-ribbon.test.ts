// E12-S07 PR B through the runtime on the fake GL: `addSeries` and `setSeriesKind` cover `line`,
// `area` and `baseline` over the same store (no data resent): 3, 4 and 6 draws over the ribbon's
// own buffer, the candle hosts hidden; a pan uploads nothing; a switch from candles uploads the
// ring once into the ribbon's buffer, and back, the candles' buffer gets every bar again;
// Heikin-Ashi on a line kind is refused and the line keeps drawing over real closes (R-4); a
// theme without `color.chart.line` refuses only the line family (BQ-7); a pick near the line
// answers the series' bar; the baseline's user B (BQ-9) is a series option.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  encodeCandles,
  ENGINE_SERIES_INCOMPATIBLE,
  type FromWorker,
} from "../../src/worker/protocol.js";
import { RIBBON_GEOM } from "../../src/layers/index.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { THEME } from "../layers/fixtures.js";

const LINE_THEME = { ...THEME, "color.chart.line": "#8b5cf6" };
let out: FromWorker[];
let rt: RenderRuntime;
let gl: FakeGl;
const frame = (ms = 16): void => void vi.advanceTimersByTime(ms);
const cmd = (c: object): void => rt.handle({ t: "command", id: 1, cmd: c });
const N = 60;
function bars(series = 0): void {
  const open = Int32Array.from({ length: N }, (_, i) => 100 + (i % 7));
  const { layout, buffer } = encodeCandles({
    time: Float64Array.from({ length: N }, (_, i) => i * 60e6),
    open,
    high: open.map((o) => o + 3),
    low: open.map((o) => o - 2),
    close: open.map((o, i) => o + ((i % 3) - 1)),
    volume: new Float32Array(N).fill(1),
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
const writes = (fn: () => void): string[] => {
  const before = gl.writes.length;
  fn();
  frame();
  return gl.writes.slice(before);
};
const errors = (): FromWorker[] => out.filter((m) => m.t === "error");
const acks = (): number => out.filter((m) => m.t === "ack").length;

function init(theme: Record<string, string> = LINE_THEME): void {
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
  rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme, config: { bench: true, syncGroup: null } });
}
beforeEach(() => {
  vi.useFakeTimers();
  init();
});
afterEach(() => {
  vi.useRealTimers();
});

const entry = (sid = 0) => {
  const s = rt.series(1, sid);
  if (s === undefined) throw new Error(`no series ${sid}`);
  return s;
};
function series(kind: string): void {
  cmd({ k: "addSeries", series: 0, kind });
  bars();
  view(0, 40); // ≈ 19 CSS px a bar
  frame();
}

describe("the line family through the runtime", () => {
  it("addSeries line: three draws (stroke and joins over every slot, one disc), no candle", () => {
    series("line");
    const s = entry();
    const cap = s.ring.capacity;
    expect(drawn(() => view(1, 41))).toEqual([`4 ${cap}`, `4 ${cap}`, "4 1"]);
    expect(s.candle.hosts.every((h) => !h.visible)).toBe(true);
    expect(s.ribbon?.blocks.map((b) => b.label).slice(3)).toEqual(
      ["stroke", "join", "last"].map((p) => `series.line.${p}`),
    );
    expect(errors()).toEqual([]);
  });

  it("a pan uploads nothing: the parts, the ring state and B are uniforms", () => {
    series("baseline");
    const before = gl.uniforms.length;
    expect(writes(() => view(3, 43))).toEqual([]);
    const base = gl.uniforms.slice(before).filter((u) => u[0] === "u_base");
    expect(base.length).toBeGreaterThan(0);
    const { store } = entry();
    // B is the first visible bar's close (bar 3), the disc's base the last close.
    const at = (i: number): number =>
      store.columns.close[(store.ringHead + i) & (store.capacity - 1)] ?? NaN;
    expect(new Set(base.map((u) => u[1]))).toEqual(new Set([at(3), at(N - 1)]));
  });

  it("candles → line → area → baseline → candles: 2, 3, 4, 6, 2 draws; no data resent", () => {
    series("candles");
    const s = entry();
    const cap = s.ring.capacity;
    const sent = acks();
    const switchTo = (kind: string): string[] =>
      drawn(() => cmd({ k: "setSeriesKind", series: 0, kind }));
    expect(switchTo("line")).toHaveLength(3);
    expect(switchTo("area")).toEqual([`4 ${cap}`, `4 ${cap}`, `4 ${cap}`, "4 1"]);
    expect(switchTo("baseline")).toEqual([
      `4 ${cap}`,
      `4 ${cap}`,
      "4 1",
      `4 ${cap}`,
      `4 ${cap}`,
      "4 1",
    ]);
    expect(switchTo("candles")).toEqual([`4 ${cap}`, `4 ${cap}`]);
    expect([acks(), entry().kind]).toEqual([sent, "candles"]);
    expect(s.ribbon?.hosts.every((h) => !h.visible)).toBe(true);
    expect(rt.seriesMetrics(1)?.switchDurationMs).toHaveProperty("baseline");
  });

  it("uploads: candles → line fills the ribbon's buffer once; line ↔ area none; back refills", () => {
    series("candles");
    const s = entry();
    const cap = s.ring.capacity;
    expect(writes(() => cmd({ k: "setSeriesKind", series: 0, kind: "line" }))).toEqual([
      `full ${(cap + 1) * 20}`, // the ring and its guard slot, the first build of the ribbon
    ]);
    expect(writes(() => cmd({ k: "setSeriesKind", series: 0, kind: "area" }))).toEqual([]);
    const back = writes(() => cmd({ k: "setSeriesKind", series: 0, kind: "candles" }));
    expect(back).toHaveLength(1); // every bar into the candles' buffer: they missed the syncs
    expect(back[0]).toMatch(/^sub /);
    expect(Number(back[0]?.split(" ")[3])).toBe(N * 5);
    expect(writes(() => cmd({ k: "setSeriesKind", series: 0, kind: "line" }))).toHaveLength(1);
  });

  it("Heikin-Ashi with a line kind is refused; the line keeps drawing real closes (R-4)", () => {
    series("candles");
    cmd({ k: "setSeriesKind", series: 0, kind: "candles", heikinAshi: true });
    frame();
    const s = entry();
    expect(s.ring.ha).not.toBeNull();
    cmd({ k: "setSeriesKind", series: 0, kind: "line" });
    frame();
    expect(s.ring.ha).toBeNull(); // the ring is plain again: the line reads the store's closes
    const close = s.store.columns.close;
    for (let i = 0; i < N; i += 1) {
      const p = (s.ring.head + i) & (s.ring.capacity - 1);
      expect(s.ring.ints[p * 5 + 3]).toBe(close[p]);
    }
    const draws = drawn(() => {
      cmd({ k: "setSeriesKind", series: 0, kind: "area", heikinAshi: true });
      view(1, 41);
    });
    expect(draws).toHaveLength(3); // still the line: the refusal changed nothing
    cmd({ k: "setSeriesOptions", series: 0, options: { heikinAshi: true } });
    frame();
    expect(errors().map((e) => (e as { code: string }).code)).toEqual([
      ENGINE_SERIES_INCOMPATIBLE,
      ENGINE_SERIES_INCOMPATIBLE,
    ]);
    expect(rt.seriesMetrics(1)?.incompatible).toEqual({
      "heikin-ashi+area": 1,
      "heikin-ashi+line": 1,
    });
    expect(entry().kind).toBe("line");
  });

  it("BQ-7: without color.chart.line only the line family is refused; candles still draw", () => {
    init(THEME);
    series("line");
    cmd({ k: "addSeries", series: 1, kind: "candles" });
    bars(1);
    frame();
    const missing = errors().map((e) => (e as { message: string }).message);
    expect(missing).toHaveLength(1);
    expect(missing[0]).toContain("color.chart.line");
    const cap = entry(1).ring.capacity;
    expect(drawn(() => view(1, 41))).toEqual([`4 ${cap}`, `4 ${cap}`]); // series 1's candles
    cmd({ k: "setTheme", theme: LINE_THEME });
    expect(drawn(() => view(2, 42))).toHaveLength(5);
  });

  it("a ribbon hidden behind candles is not themed; it is re-themed when shown again", () => {
    series("line");
    cmd({ k: "setSeriesKind", series: 0, kind: "candles" });
    frame();
    cmd({ k: "setTheme", theme: THEME }); // no color.chart.line: only the hidden family lacks it
    frame();
    expect(errors()).toEqual([]);
    expect(drawn(() => view(1, 41))).toHaveLength(2); // the candles
    cmd({ k: "setSeriesKind", series: 0, kind: "line" });
    frame();
    const missing = errors().map((e) => (e as { message: string }).message);
    expect(missing).toHaveLength(1);
    expect(missing[0]).toContain("color.chart.line");
    expect(drawn(() => view(2, 42))).toEqual([]); // refused: neither family draws
    cmd({ k: "setTheme", theme: LINE_THEME });
    expect(drawn(() => view(3, 43))).toHaveLength(3);
  });

  it("candles hidden behind a line take the theme set meanwhile when shown again", () => {
    series("line");
    cmd({ k: "setTheme", theme: { ...LINE_THEME, "color.candle.up": "#112233" } });
    frame();
    cmd({ k: "setSeriesKind", series: 0, kind: "candles" });
    frame();
    const up = Array.from(entry().candle.palette.subarray(0, 4));
    [0x11, 0x22, 0x33, 0xff].forEach((v, i) => expect(up[i]).toBeCloseTo(v / 255, 6));
    expect(errors()).toEqual([]);
  });

  it("back to candles with a theme lacking a candle token: refused, the candles stay hidden", () => {
    series("line");
    const theme: Record<string, string> = { ...LINE_THEME };
    delete theme["color.candle.down"];
    cmd({ k: "setTheme", theme });
    frame();
    expect(errors()).toEqual([]); // the hidden candles are not themed; the line needs no candle token
    cmd({ k: "setSeriesKind", series: 0, kind: "candles" });
    frame();
    const missing = errors().map((e) => (e as { message: string }).message);
    expect(missing).toHaveLength(1);
    expect(missing[0]).toContain("color.candle.down");
    expect(entry().candle.hosts.some((h) => h.visible)).toBe(false);
    expect(drawn(() => view(1, 41))).toEqual([]);
  });

  it("a degraded-2d re-init drops a hidden ribbon; a later line kind mounts one afresh", () => {
    series("line");
    cmd({ k: "setSeriesKind", series: 0, kind: "candles" });
    frame();
    const old = entry().ribbon;
    expect(old?.active).toBe(false);
    rt.handle({
      t: "init",
      id: 1,
      canvas: { width: 800, height: 400, getContext: () => null },
      dpr: 1,
      theme: LINE_THEME,
      config: { bench: true, syncGroup: null },
      profile: "degraded-2d",
    });
    expect(entry().ribbon).toBeNull();
    expect(entry().candle.hosts.every((h) => h.visible)).toBe(true);
    cmd({ k: "setSeriesKind", series: 0, kind: "line" });
    const fresh = entry().ribbon;
    expect(fresh).not.toBeNull();
    expect(fresh).not.toBe(old);
    const graph = rt.graph(1);
    expect(fresh?.hosts.map((h) => graph?.get(h.id) === h)).toEqual(Array(6).fill(true));
    expect(old?.hosts.some((h) => graph?.get(h.id) !== undefined)).toBe(false);
    expect(fresh?.hosts.every((h) => h.visible)).toBe(true);
    expect(entry().ring.nodes).toEqual(fresh?.hosts.map((h) => h.id));
  });

  it("a plain line draws with color.chart.line alone; area then asks for the canvas", () => {
    init({ "color.chart.line": "#8b5cf6" });
    series("line");
    expect(errors()).toEqual([]);
    expect(drawn(() => view(1, 41))).toHaveLength(3);
    cmd({ k: "setSeriesKind", series: 0, kind: "area" });
    frame();
    const codes = errors().map((e) => (e as { message: string }).message);
    expect(codes.some((m) => m.includes("color.surface.canvas"))).toBe(true);
  });

  it("a pick near the line answers the series' bar; far above and below, none", () => {
    series("line");
    for (let y = 0; y < 400; y += 2) cmd({ k: "pickAt", x: 300, y, reqId: y });
    const picks = out.filter((m) => m.t === "pick") as { kind: string; objectId: string }[];
    const hits = picks.filter((p) => p.kind === "bar");
    expect(hits.length).toBeGreaterThan(0);
    expect(hits.every((p) => p.objectId === "series.0")).toBe(true);
    expect(picks.length - hits.length).toBeGreaterThan(0);
    expect(entry().ribbon?.active).toBe(true);
  });

  it("BQ-9: the baseline option sets B (a tick), null restores the first visible close", () => {
    series("baseline");
    cmd({ k: "setSeriesOptions", series: 0, options: { baseline: 104 } });
    frame();
    const r = entry().ribbon;
    expect(r?.blocks.slice(0, 3).map((b) => b.base)).toEqual([104, 104, 104]);
    cmd({ k: "setSeriesOptions", series: 0, options: { baseline: null } });
    frame();
    expect(r?.baseTick).toBeNull();
    cmd({ k: "setSeriesOptions", series: 0, options: { baseline: 1.5 } }); // not a tick: ignored
    expect(r?.baseTick).toBeNull();
    // `u_base` is a GLSL int: a safe integer outside the int32 tick window is refused too.
    for (const out of [2 ** 31, -(2 ** 31), 2 ** 40, 2 ** 30]) {
      cmd({ k: "setSeriesOptions", series: 0, options: { baseline: out } });
      expect(r?.baseTick).toBeNull();
    }
    cmd({ k: "setSeriesOptions", series: 0, options: { baseline: 2 ** 30 - 1 } });
    expect(r?.baseTick).toBe(2 ** 30 - 1);
  });

  it("the frame hands the ribbon the plot rect: the base line stops short of the gutter", () => {
    series("baseline");
    frame();
    const g = entry().ribbon?.geom;
    expect(g?.[RIBBON_GEOM.plotRight] ?? 0).toBeGreaterThan(0);
    expect(g?.[RIBBON_GEOM.plotBottom] ?? 0).toBeGreaterThan(0);
  });

  it("removeSeries hides the ribbon's hosts and drops its blocks", () => {
    series("area");
    const r = entry().ribbon;
    cmd({ k: "removeSeries", series: 0 });
    expect(drawn(() => view(1, 41))).toEqual([]);
    expect(r?.hosts.every((h) => !h.visible)).toBe(true);
  });
});
