// E12-S06 candle drawing through the runtime on the fake GL: exactly two instanced draws per
// series (wick, body; BQ-1) over ONE shared buffer, the int attributes bound once, a theme switch
// and a pan upload nothing, a context restore re-uploads from the CPU ring, and a theme missing a
// candle token is a recoverable error with no series drawn (BQ-4).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ENGINE_THEME_TOKEN_MISSING } from "../../src/layers/index.js";
import { encodeCandles, type FromWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { THEME } from "../layers/fixtures.js";

type Listener = (ev: { preventDefault(): void }) => void;
let out: FromWorker[];
let rt: RenderRuntime;
let gl: FakeGl;
const on = new Map<string, Listener>();
const frame = (ms = 16): void => void vi.advanceTimersByTime(ms);
const cmd = (c: object): void => rt.handle({ t: "command", id: 1, cmd: c });
const bars = (m: number, n: number, op = "replace"): void => {
  const open = Int32Array.from({ length: n }, (_, i) => 100 + ((m + i) % 7));
  const { layout, buffer } = encodeCandles({
    time: Float64Array.from({ length: n }, (_, i) => (m + i) * 60e6),
    open,
    high: open.map((o) => o + 3),
    low: open.map((o) => o - 2),
    close: open.map((o, i) => o + ((i % 3) - 1)),
    volume: new Float32Array(n).fill(1),
    priceOrigin: 0,
    tickSize: 1,
  });
  rt.handle({ t: "data", id: 1, store: "bars", op, layout, buffer, series: 0 });
};
const mark = (): { draws: number; writes: number; attribs: number } => ({
  draws: gl.draws.length,
  writes: gl.writes.length,
  attribs: gl.attribs.length,
});

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  on.clear();
  gl = new FakeGl({ params: ROOMY });
  gl.trackDraws = true;
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
  });
  const canvas = {
    width: 800,
    height: 400,
    getContext: () => gl,
    addEventListener: (type: string, cb: Listener) => void on.set(type, cb),
    removeEventListener: (type: string) => void on.delete(type),
  };
  rt.handle({
    t: "init",
    id: 1,
    canvas,
    dpr: 1,
    theme: THEME,
    config: { bench: true, syncGroup: null },
  });
  cmd({ k: "addSeries", series: 0, kind: "candles" });
  bars(0, 300);
  frame();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("candle drawing (BQ-1)", () => {
  it("draws each series in exactly two instanced draws over one shared buffer", () => {
    const capacity = rt.series(1, 0)?.ring.capacity;
    expect(gl.draws).toEqual([`4 ${capacity}`, `4 ${capacity}`]);
    // The ring once for both parts; the gap seams' 16-entry buffer once (no gap: never drawn).
    expect(gl.writes.filter((w) => w.startsWith("full"))).toEqual([
      `full ${(capacity ?? 0) * 20}`,
      `full ${16 * 20}`,
    ]);
    const vao = ["attrib 0 4 20 0", "divisor 0 1", "attrib 1 1 20 16", "divisor 1 1"];
    expect(gl.attribs).toEqual([...vao, ...vao, ...vao]);
    const batch = gl.uniforms.filter((u) => u[0] === "u_batch");
    expect(batch.map((u) => u.slice(1))).toEqual([
      [0, rt.series(1, 0)?.ring.head, (capacity ?? 0) - 1, 300],
      [1, rt.series(1, 0)?.ring.head, (capacity ?? 0) - 1, 300],
    ]);
    expect(gl.uniforms.find((u) => u[0] === "u_palette")).toHaveLength(25);
  });

  it("a live append uploads only the new bar, once for both parts, and still draws twice", () => {
    const before = mark();
    bars(300, 1, "append");
    frame();
    const now = gl.writes.slice(before.writes);
    expect(now).toEqual([
      `sub ${(rt.series(1, 0)?.ring.head ?? 0) * 20 + 300 * 20} ${(rt.series(1, 0)?.ring.head ?? 0) * 5 + 300 * 5} 5`,
    ]);
    expect(gl.draws.length - before.draws).toBe(2);
  });

  it("a theme switch rewrites the palette uniforms only: no buffer upload", () => {
    const before = mark();
    cmd({ k: "setTheme", theme: { ...THEME, "color.candle.up": "#00ff00" } });
    frame();
    expect(gl.writes.length - before.writes).toBe(0);
    const palette = gl.uniforms.filter((u) => u[0] === "u_palette").at(-1);
    expect(palette?.slice(1, 5)).toEqual([0, 1, 0, 1]);
  });

  it("a pan is uniform writes only: no upload, two draws", () => {
    const before = mark();
    rt.handle({ t: "input", id: 1, kind: "key", events: Float32Array.of(4, 3, 0, 0, 0, 16) });
    frame();
    expect([gl.writes.length - before.writes, gl.draws.length - before.draws]).toEqual([0, 2]);
  });

  it("a theme missing a candle token is a recoverable error and no series drawn (BQ-4)", () => {
    const before = mark();
    cmd({ k: "setTheme", theme: { ...THEME, "color.candle.wick": undefined } });
    frame();
    expect(out.filter((m) => m.t === "error").map((m) => (m as { code: string }).code)).toEqual([
      ENGINE_THEME_TOKEN_MISSING,
    ]);
    expect(gl.draws.length - before.draws).toBe(0);
    cmd({ k: "setTheme", theme: THEME });
    frame();
    expect(gl.draws.length - before.draws).toBe(2);
  });

  it("a context restore re-uploads the ring from the CPU and rebinds the attributes", () => {
    gl.loseContext();
    on.get("webglcontextlost")?.({ preventDefault: () => undefined });
    frame(500);
    gl.restoreContext();
    const before = mark();
    on.get("webglcontextrestored")?.({ preventDefault: () => undefined });
    frame();
    const capacity = rt.series(1, 0)?.ring.capacity ?? 0;
    expect(gl.writes.slice(before.writes)).toEqual([`full ${capacity * 20}`, `full ${16 * 20}`]);
    expect(gl.attribs.length - before.attribs).toBe(12);
    expect(gl.draws.length - before.draws).toBe(2);
  });

  it("removing the series stops its draws", () => {
    const before = mark();
    cmd({ k: "removeSeries", series: 0 });
    frame();
    expect(gl.draws.length - before.draws).toBe(0);
  });
});
