// E11-S06 through the runtime and the fake GL (README C-66, BQ-9, BQ-193): the axes' grid is
// attached as its own instance ring and drawn in one `line` draw, hidden while the visible
// range is empty, rewritten in place when a pan changes the axes (series buffers upload
// nothing), and re-uploaded in full after a context restore. Frames by hand on fake timers.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { encodeCandles, INPUT, type FromWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { rows } from "../interaction/fixtures.js";
import { THEME } from "../layers/fixtures.js";

type Listener = (ev: { preventDefault(): void }) => void;
let out: FromWorker[];
let rt: RenderRuntime;
let gl: FakeGl;
const on = new Map<string, Listener>();
const frame = (ms = 16): void => void vi.advanceTimersByTime(ms);
const bars = (n: number): void => {
  const open = Int32Array.from({ length: n }, (_, i) => 64_000 + (i % 40));
  const { layout, buffer } = encodeCandles({
    time: Float64Array.from({ length: n }, (_, i) => Date.UTC(2026, 0, 5) * 1000 + i * 60e6),
    open,
    high: open.map((o) => o + 6),
    low: open.map((o) => o - 5),
    close: open.map((o, i) => o + ((i % 3) - 1)),
    volume: new Float32Array(n).fill(1),
    priceOrigin: 0,
    tickSize: 1,
  });
  rt.handle({ t: "data", id: 1, store: "bars", op: "replace", layout, buffer, series: 0 });
};
const mark = (): { ints: number; floats: number; draws: number } => ({
  ints: gl.intWrites().length,
  floats: gl.floatWrites().length,
  draws: gl.floatDraws().length,
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
  const config = { bench: true, syncGroup: null };
  rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme: THEME, config });
  rt.handle({ t: "command", id: 1, cmd: { k: "addSeries", series: 0, kind: "candles" } });
  bars(300);
  frame();
  frame();
});

afterEach(() => {
  vi.useRealTimers();
});

const frames = (): Extract<FromWorker, { t: "frame" }>[] =>
  out.filter((m): m is Extract<FromWorker, { t: "frame" }> => m.t === "frame");
const drag = (type: number, x: number, dt = 0): void =>
  rt.handle({ t: "input", id: 1, kind: "pointer", events: rows([type, x, 200, 1, 0, dt]) });
/** Lines in the grid's last draw: `4 <instances>`. */
const lines = (): number => Number((gl.floatDraws().at(-1) ?? "4 0").split(" ")[1]);

describe("the axes' grid through the GL backend (E11-S06)", () => {
  it("is attached as its own float ring, uploaded once in full and drawn in one `line` draw", () => {
    // The first drawn frame: the series' int rings and the grid's float ring, each in full.
    expect(gl.floatWrites()).toEqual([`full ${128 * 9 * 4}`]); // 128 lines' worth, 9 floats each
    expect(gl.floatDraws()).toHaveLength(1);
    expect(lines()).toBeGreaterThan(4); // price and time lines plus the two axis rules
    expect(gl.intDraws()).toHaveLength(2); // the candles' wick and body, unchanged
    const before = mark();
    rt.handle({ t: "resize", id: 1, width: 800, height: 400, dpr: 1 }); // a frame, nothing moved
    frame();
    expect(gl.floatDraws().length - before.draws).toBe(1); // one grid draw a frame
    expect(gl.floatWrites().length - before.floats).toBe(0); // a still frame rewrites nothing
    expect(frames().at(-1)?.uploadedBytes).toBe(0);
  });

  it("a pan rewrites only the grid's ring, in place, and no series buffer (C-66)", () => {
    const before = mark();
    drag(INPUT.down, 300);
    drag(INPUT.move, 340);
    frame();
    expect(gl.intWrites().length).toBe(before.ints); // series: 0 bytes
    const grid = gl.floatWrites().slice(before.floats);
    expect(grid).toEqual([`sub 0 0 ${lines() * 9}`]); // one write of exactly the drawn lines
    expect(frames().at(-1)?.uploadedBytes).toBe(lines() * 36); // 36 B a line, nothing else
    expect(gl.floatDraws().length - before.draws).toBe(1);
  });

  it("a scale change with bars in view writes the grid once and no series buffer (C-66)", () => {
    const before = mark();
    rt.handle({ t: "command", id: 1, cmd: { k: "setPriceScale", pane: 0, mode: "percent" } });
    frame();
    expect(gl.intWrites().length).toBe(before.ints); // the series half: exactly 0 writes
    expect(gl.floatWrites().slice(before.floats)).toEqual([`sub 0 0 ${lines() * 9}`]);
    expect(frames().at(-1)?.uploadedBytes).toBe(lines() * 36);
  });

  it("is hidden while the visible range is empty, and drawn again once bars return (BQ-9)", () => {
    const before = mark();
    bars(0);
    frame();
    expect(out.filter((m) => m.t === "dataState").at(-1)).toMatchObject({ state: "empty" });
    expect(gl.floatDraws().length - before.draws).toBe(0); // the background layer is hidden
    bars(300);
    frame();
    expect(out.filter((m) => m.t === "dataState").at(-1)).toMatchObject({ state: "ready" });
    expect(gl.floatDraws().length - before.draws).toBe(1);
    expect(lines()).toBeGreaterThan(4);
  });

  it("a context restore uploads the ring in full and rewrites it from fresh axes", () => {
    gl.loseContext();
    on.get("webglcontextlost")?.({ preventDefault: () => undefined });
    frame(1_000);
    gl.restoreContext();
    const before = mark();
    on.get("webglcontextrestored")?.({ preventDefault: () => undefined });
    frame();
    // The restore's full upload (held at the loss), then the rebuilt axes' rewrite (`invalidate`).
    expect(gl.floatWrites().slice(before.floats)).toEqual([
      `full ${128 * 9 * 4}`,
      `sub 0 0 ${lines() * 9}`,
    ]);
    expect(gl.floatDraws().length - before.draws).toBe(1);
  });
});
