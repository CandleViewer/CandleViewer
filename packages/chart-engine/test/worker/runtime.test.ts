// The render runtime on a synchronous bus (E11-T02): the one implementation both run modes use.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NO_WEBGL2_REASON } from "../../src/gl/capability.js";
import { probeWorker, startWorker } from "../../src/worker/render-worker.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import {
  BACKGROUND_TOKEN,
  ENGINE_DECODE_ERROR,
  INPUT,
  KEY,
  type FromWorker,
  type ToWorker,
} from "../../src/worker/protocol.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";

interface Ctx {
  fillStyle: unknown;
  fills: string[];
  clearRect(): void;
  fillRect(): void;
}

function canvas(
  width = 200,
  height = 100,
): { width: number; height: number; ctx: Ctx; getContext(): Ctx } {
  const ctx: Ctx = {
    fillStyle: "",
    fills: [],
    clearRect: () => undefined,
    fillRect(): void {
      this.fills.push(String(this.fillStyle));
    },
  };
  return { width, height, ctx, getContext: () => ctx };
}

let out: FromWorker[];
let probes: number;
let rt: RenderRuntime;
const frame = (): void => {
  vi.advanceTimersByTime(16);
};
const of = <T extends FromWorker["t"]>(t: T): Extract<FromWorker, { t: T }>[] =>
  out.filter((m): m is Extract<FromWorker, { t: T }> => m.t === t);

function make(
  bench = false,
  syncGroup: string | null = null,
  id = 1,
  c = canvas(),
): ReturnType<typeof canvas> {
  rt.handle({
    t: "init",
    id,
    canvas: c,
    dpr: 1,
    theme: { [BACKGROUND_TOKEN]: "#000000" },
    config: { bench, syncGroup },
  } satisfies ToWorker);
  return c;
}

const row = (type: number, x: number, buttons = 0): Float32Array =>
  new Float32Array([type, x, 0, buttons, 0, 0]);

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  probes = 0;
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => {
      setTimeout(cb, 16);
    },
    now: () => Date.now(),
    probe: () => {
      probes += 1;
      return FULL;
    },
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("render loop", () => {
  it("reports ready once per chart on its first frame, probing once per runtime", () => {
    const a = make(false, null, 1);
    make(false, null, 2);
    expect(out).toEqual([]);
    frame();
    expect(of("ready")).toEqual([
      { t: "ready", id: 1, runMode: "inline", renderProfile: "full", capabilities: FULL },
      { t: "ready", id: 2, runMode: "inline", renderProfile: "full", capabilities: FULL },
    ]);
    expect(probes).toBe(1);
    expect(a.ctx.fills).toEqual(["#000000"]);
    expect(rt.size).toBe(2);
  });

  it("parks when nothing is dirty and samples frame stats at 1 Hz", () => {
    make();
    frame();
    expect(of("frame")).toHaveLength(1);
    rt.handle({ t: "command", id: 1, cmd: { k: "setLod", candles: 1, footprint: 2 } });
    frame();
    expect(of("frame")).toHaveLength(1); // within the second: rendered, not reported
    vi.advanceTimersByTime(1000);
    expect(of("frame")).toHaveLength(1); // parked: no frame without work
    rt.handle({ t: "command", id: 1, cmd: { k: "setSeriesOptions", series: 0, options: {} } });
    frame();
    expect(of("frame").at(-1)?.lod).toEqual({ candles: 1, footprint: 2 });
  });

  it("reports every frame in bench mode (the LOD trace hook)", () => {
    make(true);
    for (let i = 0; i < 3; i += 1) {
      rt.handle({
        t: "command",
        id: 1,
        cmd: { k: "setLod", candles: (i % 3) as 0 | 1 | 2, footprint: 0 },
      });
      frame();
    }
    expect(of("frame").map((f) => f.lod.candles)).toEqual([0, 1, 2]);
  });

  it("repaints with the new theme and on resize", () => {
    const c = make();
    frame();
    rt.handle({ t: "command", id: 1, cmd: { k: "setTheme", theme: {} } });
    frame();
    expect(c.ctx.fills).toEqual(["#000000"]); // no background token: cleared only
    rt.handle({ t: "resize", id: 1, width: 50, height: 40, dpr: 2 });
    frame();
    expect([c.width, c.height]).toEqual([100, 80]);
  });
});

describe("the frame scheduler in the runtime (E11-S01 PR3)", () => {
  it("forwards budget and LOD step-down notices as recoverable errors; lodCandles shows it", () => {
    const c = make(true);
    const fake = (): number => vi.getMockedSystemTime()?.getTime() ?? 0; // fake timers, not wall
    c.ctx.fillRect = (): void => void vi.setSystemTime(fake() + 20); // each frame costs 20 ms
    for (let f = 0; f < 4; f += 1) {
      rt.handle({ t: "command", id: 1, cmd: { k: "setViewport", timeStart: f, timeEnd: 9 } });
      frame();
    }
    const codes = of("error").map((e) => [e.code, e.recoverable]);
    expect(codes).toEqual([
      ["ENGINE_FRAME_BUDGET_EXCEEDED", true],
      ["ENGINE_LOD_STEPDOWN", true],
    ]);
    expect(of("error")[1]?.message).toMatch(/^LOD 0 -> 1; frame 20\.00 ms, worst stage compo/);
    expect(of("frame").map((m) => m.lod.candles)).toEqual([0, 0, 0, 1]);
    rt.handle({ t: "command", id: 1, cmd: { k: "release" } });
    rt.handle({ t: "command", id: 1, cmd: { k: "setViewport", timeStart: 0, timeEnd: 9 } });
    frame();
    expect(of("frame")).toHaveLength(4); // released: its scheduler is disposed
  });
});

describe("interaction", () => {
  it("pans on drag, zooms at the cursor, reports the crosshair and posts viewport once per frame", () => {
    make();
    rt.handle({ t: "command", id: 1, cmd: { k: "setViewport", timeStart: 0, timeEnd: 2e9 } });
    rt.handle({ t: "input", id: 1, kind: "pointer", events: row(INPUT.down, 100) });
    rt.handle({ t: "input", id: 1, kind: "pointer", events: row(INPUT.move, 150, 1) });
    rt.handle({ t: "input", id: 1, kind: "pointer", events: row(INPUT.up, 150) });
    frame();
    expect(of("viewport")).toEqual([
      {
        t: "viewport",
        id: 1,
        timeStart: -5e8,
        timeEnd: 1.5e9,
        priceLow: 0,
        priceHigh: 0,
        barSpacing: 0,
      },
    ]);
    expect(of("a11y")).toHaveLength(1);
    rt.handle({ t: "input", id: 1, kind: "wheel", events: row(INPUT.wheel, 0, 500) });
    rt.handle({ t: "input", id: 1, kind: "key", events: row(INPUT.key, KEY.zoomIn) });
    rt.handle({ t: "input", id: 1, kind: "key", events: row(INPUT.key, 9) }); // unbound key
    frame();
    const vp = of("viewport").at(-1);
    // The wheel zooms by e at x = 0, the key by 0.8 at the centre.
    expect(((vp?.timeEnd ?? 0) - (vp?.timeStart ?? 0)) / 2e9).toBeCloseTo(Math.exp(1) * 0.8, 9);
    rt.handle({ t: "input", id: 1, kind: "touch", events: row(INPUT.move, 150) });
    frame();
    expect(of("a11y")).toHaveLength(2);
  });

  it("applies a sync to its group only", () => {
    make(false, "g", 1);
    make(false, "other", 2);
    rt.handle({ t: "sync", groupId: "g", timeRange: [10, 20], crosshair: 15 });
    frame();
    expect(of("viewport").map((v) => v.id)).toEqual([1]);
    expect(of("a11y")).toEqual([{ t: "a11y", id: 1, cursorSummary: "1970-01-01T00:00:00.000Z" }]);
    rt.handle({ t: "sync", groupId: "g", timeRange: [10, 20], crosshair: null });
    frame();
    expect(of("a11y").at(-1)?.cursorSummary).toBe("");
  });

  it("reports a pick edge-triggered", () => {
    make();
    rt.handle({ t: "command", id: 1, cmd: { k: "pickAt", x: 1, y: 1 } });
    rt.handle({ t: "command", id: 1, cmd: { k: "pickAt", x: 2, y: 2 } });
    expect(of("pick")).toHaveLength(1);
    expect(of("pick")[0]?.objectId).toBeNull();
  });

  it("ignores degenerate ranges and an empty canvas width", () => {
    make(false, null, 1, canvas(0, 0));
    rt.handle({ t: "input", id: 1, kind: "pointer", events: row(INPUT.down, 0) });
    rt.handle({ t: "input", id: 1, kind: "pointer", events: row(INPUT.move, 5, 1) });
    rt.handle({ t: "input", id: 1, kind: "wheel", events: row(INPUT.wheel, 0, 1e9) });
    frame();
    expect(of("viewport")).toEqual([]);
  });
});

describe("data and export", () => {
  it("acknowledges every batch and releases a chart", () => {
    make();
    for (const op of ["replace", "append", "prepend", "patch"] as const) {
      rt.handle({
        t: "data",
        id: 1,
        store: "bars",
        op,
        layout: { count: 1, columns: [{ offset: 0, bytes: 8 }], params: [] },
        buffer: new ArrayBuffer(8),
      });
    }
    expect(of("ack")).toHaveLength(4);
    rt.handle({ t: "command", id: 1, cmd: { k: "release" } });
    expect(rt.size).toBe(0);
  });

  it("exports through convertToBlob, toBlob, or reports null", async () => {
    const blob = { png: true };
    const off = { ...canvas(), convertToBlob: () => Promise.resolve(blob) };
    const broken = { ...canvas(), convertToBlob: () => Promise.reject(new Error("x")) };
    const el = { ...canvas(), toBlob: (cb: (b: unknown) => void) => cb(blob) };
    make(false, null, 1, off);
    make(false, null, 2, broken);
    make(false, null, 3, el);
    make(false, null, 4, canvas());
    for (const id of [1, 2, 3, 4]) rt.handle({ t: "command", id, cmd: { k: "export", reqId: id } });
    await vi.runAllTimersAsync();
    expect(of("exported").map((m) => [m.id, m.blob])).toEqual(
      expect.arrayContaining([
        [1, blob],
        [2, null],
        [3, blob],
        [4, null],
      ]),
    );
  });
});

describe("Scenario: A malformed message cannot kill the worker", () => {
  it("rejects the short bars buffer with a recoverable ENGINE_DECODE_ERROR and keeps rendering", () => {
    const c = make();
    frame();
    rt.handle({
      t: "data",
      id: 1,
      store: "bars",
      op: "append",
      layout: { count: 2, columns: [{ offset: 0, bytes: 8 }], params: [] },
      buffer: new ArrayBuffer(13),
    });
    expect(of("error")).toEqual([
      {
        t: "error",
        id: 1,
        code: ENGINE_DECODE_ERROR,
        message: "buffer length does not match its layout",
        recoverable: true,
      },
    ]);
    expect(of("ack")).toHaveLength(1); // the backpressure slot is released
    rt.handle({
      t: "command",
      id: 1,
      cmd: { k: "setTheme", theme: { [BACKGROUND_TOKEN]: "#000000" } },
    });
    frame();
    expect(c.ctx.fills).toEqual(["#000000", "#000000"]); // the previous contents, still rendering
  });

  it("reports messages for an unknown chart and a throwing canvas without throwing", () => {
    make();
    rt.handle({ t: "resize", id: 9, width: 1, height: 1, dpr: 1 });
    expect(of("error")[0]?.message).toBe("no chart 9 on this worker");
    const hostile = {
      get width(): number {
        throw new Error("boom");
      },
    };
    expect(() => make(false, null, 3, hostile as never)).not.toThrow();
    expect(of("error").at(-1)).toMatchObject({ id: null, message: "boom" });
    rt.handle({ t: "data", id: 1, store: "toString", op: "append" });
    expect(of("ack")).toEqual([]);
  });

  it("rejects an init without a canvas and contains a canvas that throws while rendering", () => {
    rt.handle({ t: "init", id: 2, canvas: {}, dpr: 1, theme: {}, config: {} });
    expect(of("error").at(-1)).toMatchObject({ id: 2, message: "malformed init" });
    const good = make(false, null, 1);
    const bad = {
      ...canvas(),
      getContext(): never {
        throw new Error("context lost");
      },
    };
    make(false, null, 3, bad as never);
    expect(() => frame()).not.toThrow();
    expect(of("error").at(-1)).toMatchObject({
      id: 3,
      code: ENGINE_DECODE_ERROR,
      message: "context lost",
      recoverable: true,
    });
    expect(good.ctx.fills).toEqual(["#000000"]); // the healthy chart still rendered
    rt.handle({ t: "resize", id: 3, width: 10, height: 10, dpr: 1 });
    expect(() => frame()).not.toThrow(); // and the next frame is contained as well
    expect(of("error").filter((e) => e.id === 3)).toHaveLength(2);
  });

  it("survives 10k randomly corrupted messages with zero throws", () => {
    make();
    let seed = 20261029;
    const rand = (): number => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 2 ** 32;
    };
    const pick = <T>(xs: readonly T[]): T => xs[Math.floor(rand() * xs.length)] as T;
    const kinds = ["init", "resize", "input", "data", "command", "sync", "boom", undefined];
    const junk = [
      Number.NaN,
      -1,
      1,
      1e12,
      "x",
      null,
      {},
      [],
      new ArrayBuffer(3),
      new Float32Array(7),
    ];
    const throwing = (): object => ({
      ...canvas(),
      getContext(): never {
        throw new Error("x");
      },
    });
    const badCanvases = [canvas, canvas, throwing, () => ({}), () => null, () => 5];
    let threw = 0;
    for (let i = 0; i < 10_000; i += 1) {
      const msg: Record<string, unknown> = {
        t: pick(kinds),
        id: rand() < 0.7 ? 1 : pick(junk),
        store: pick(["bars", "orders", 3]),
        op: pick(["append", "x"]),
        layout: {
          count: Math.floor(rand() * 4),
          columns: [{ offset: pick([0, 3, -8]), bytes: pick([8, 3]) }],
          params: [],
        },
        buffer: new ArrayBuffer(Math.floor(rand() * 40)),
        kind: pick(["pointer", "wheel", "nope"]),
        events: new Float32Array(
          [rand() < 0.5 ? Number.NaN : 1, 0, 0, 0, 0, 0].slice(0, pick([5, 6])),
        ),
        cmd: {
          k: pick(["setViewport", "pickAt", "zap"]),
          timeStart: pick(junk),
          timeEnd: 5,
          x: pick(junk),
          y: 1,
        },
        width: pick(junk),
        height: 5,
        dpr: pick(junk),
        groupId: pick(["g", 5]),
        timeRange: [pick(junk), 2],
        crosshair: pick(junk),
      };
      if (msg["t"] === "init") msg["canvas"] = pick(badCanvases)();
      try {
        rt.handle(msg);
      } catch {
        threw += 1;
      }
      if (i % 500 === 0) frame(); // a throwing canvas must not escape the frame callback either
    }
    frame();
    expect(threw).toBe(0);
    expect(of("error").length).toBeGreaterThan(5000);
    expect(of("error").every((e) => e.recoverable)).toBe(true);
  });
});

describe("worker entry", () => {
  it("wires the runtime to the scope and probes WebGL2 on an OffscreenCanvas", () => {
    const posted: unknown[] = [];
    const scope = {
      onmessage: null as ((ev: { data: unknown }) => void) | null,
      postMessage: (m: unknown) => posted.push(m),
      requestAnimationFrame: (cb: () => void) => setTimeout(cb, 16) as unknown as number,
    };
    startWorker(scope);
    scope.onmessage?.({ data: { t: "boom" } });
    expect(posted).toHaveLength(1);
    scope.onmessage?.({
      data: {
        t: "init",
        id: 1,
        canvas: canvas(),
        dpr: 1,
        theme: {},
        config: { bench: false, syncGroup: null },
      },
    });
    frame();
    expect(posted).toContainEqual({
      t: "ready",
      id: 1,
      runMode: "worker",
      renderProfile: "degraded-2d",
      capabilities: { profile: "degraded-2d", reasons: [NO_WEBGL2_REASON], caps: null },
    });
    const gl = class {
      getContext(): unknown {
        return new FakeGl({ params: ROOMY });
      }
    };
    const throws = class {
      constructor() {
        throw new Error("no");
      }
    };
    expect(probeWorker({ ...scope, OffscreenCanvas: gl }).profile).toBe("full");
    expect(probeWorker({ ...scope, OffscreenCanvas: throws as never }).profile).toBe("degraded-2d");
  });
});
