// E11-S02 PR3: the runtime's context-loss wiring (BQ-49) and the host's degraded-2d handoff
// (BQ-53, BQ-54) in both run modes (BQ-58), on fake timers and the fake GL.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GLBackend } from "../../src/gl/backend.js";
import { createChartHost } from "../../src/worker/host.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import {
  ENGINE_CONTEXT_LOST,
  ENGINE_CONTEXT_RESTORE_FAILED,
  ENGINE_CONTEXT_RESTORED,
  ENGINE_SHADER_COMPILE_FAILED,
  type FromWorker,
  type RunMode,
} from "../../src/worker/protocol.js";
import { asHtml, FakeDocument, type FakeElement } from "../api/fake-dom.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { fakeEnv, FakeWorker } from "./fake-worker.js";

type Listener = (ev: { preventDefault(): void }) => void;

/** A canvas holding `gl` (or no WebGL2) that fires the two context events on demand. */
function glCanvas(gl: FakeGl | null) {
  const on = new Map<string, Listener>();
  const asked: string[] = [];
  let prevented = 0;
  const ctx2d = { fillStyle: "", clearRect: () => undefined, fillRect: () => undefined };
  return {
    width: 200,
    height: 100,
    asked,
    on,
    prevented: () => prevented,
    getContext: (id: string): unknown => (asked.push(id), id === "webgl2" ? gl : ctx2d),
    addEventListener: (type: string, cb: Listener) => void on.set(type, cb),
    removeEventListener: (type: string) => void on.delete(type),
    fire: (type: string) => on.get(type)?.({ preventDefault: () => (prevented += 1) }),
  };
}

let out: FromWorker[];
let rt: RenderRuntime;
const frame = (ms = 16): void => {
  vi.advanceTimersByTime(ms);
};
const errors = (): [string, boolean][] =>
  out.flatMap((m) => (m.t === "error" ? [[m.code, m.recoverable] as [string, boolean]] : []));
const frames = (): number => out.filter((m) => m.t === "frame").length;
const base = { t: "init", id: 1, dpr: 1, theme: {}, config: { bench: true, syncGroup: null } };
const init = (canvas: object, profile?: "degraded-2d"): void =>
  rt.handle({ ...base, canvas, ...(profile && { profile }) });
const nudge = (): void => rt.handle({ t: "resize", id: 1, width: 200, height: 100, dpr: 1 });
const noop = (): void => undefined;

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()), // the fake clock
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Scenario: Context loss recovers within the R1 exit budget (the runtime)", () => {
  it("parks on loss, rebuilds on restore and reports RESTORED on the first complete frame", () => {
    const gl = new FakeGl({ params: ROOMY });
    const c = glCanvas(gl);
    init(c);
    frame();
    const before = frames();
    gl.loseContext();
    c.fire("webglcontextlost");
    expect(c.prevented()).toBe(1);
    nudge();
    frame();
    frame();
    expect(frames()).toBe(before); // parked: no frame runs, nothing spins
    frame(500);
    gl.restoreContext();
    const from = gl.log.length;
    c.fire("webglcontextrestored");
    frame();
    expect(frames()).toBe(before + 1);
    expect(errors()).toEqual([
      [ENGINE_CONTEXT_LOST, true],
      [ENGINE_CONTEXT_RESTORED, true],
    ]);
    const restored = out.filter((m) => m.t === "error").at(-1);
    expect(restored).toMatchObject({
      message: expect.stringMatching(/^Chart restored in \d+ ms$/),
    });
    expect(gl.log.slice(from)).toContain("clear"); // the frame after the rebuild drew
    const details = out.flatMap((m) => (m.t === "error" ? [m.details] : []));
    expect(details).toEqual([{ attempt: 1, maxAttempts: 3, nextTryMs: 1000 }, undefined]);
  });

  it("a chart released mid-loss posts nothing more when the attempt's timer fires", () => {
    const gl = new FakeGl({ params: ROOMY });
    const c = glCanvas(gl);
    init(c);
    frame();
    gl.loseContext();
    c.fire("webglcontextlost");
    rt.handle({ t: "command", id: 1, cmd: { k: "release" } });
    frame(10_000);
    expect(errors()).toEqual([[ENGINE_CONTEXT_LOST, true]]);
  });
});

describe("Scenario: Repeated loss gives up gracefully rather than looping (the runtime)", () => {
  it("posts RESTORE_FAILED after 1 + 2 + 4 s, stays parked, then re-inits 2D on a new canvas", () => {
    const gl = new FakeGl({ params: ROOMY });
    const c = glCanvas(gl);
    init(c);
    frame();
    const before = frames();
    gl.loseContext();
    c.fire("webglcontextlost");
    frame(7000);
    const lost = [ENGINE_CONTEXT_LOST, true] as const;
    expect(errors()).toEqual([lost, lost, lost, [ENGINE_CONTEXT_RESTORE_FAILED, false]]);
    gl.restoreContext();
    c.fire("webglcontextrestored");
    nudge();
    frame(60_000);
    expect([frames(), errors().length]).toEqual([before, 4]); // parked for good, never looping
    const next = glCanvas(new FakeGl({ params: ROOMY })); // the host's handoff (BQ-53)
    init(next, "degraded-2d");
    frame();
    expect([c.on.size, next.asked]).toEqual([0, ["2d"]]); // old listeners gone; no WebGL2 asked
    const ready = out.flatMap((m) => (m.t === "ready" ? [m.renderProfile] : []));
    expect([ready, errors().length]).toEqual([["full", "degraded-2d"], 4]); // no ENGINE_NO_WEBGL2
  });
});

/** A host on the fake DOM in `mode`; `canvases` records every canvas it was handed. */
function mountHost(mode: RunMode) {
  const doc = new FakeDocument();
  doc.offscreenAvailable = mode === "worker";
  doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
  let canvas: FakeElement = doc.createElement("canvas");
  const canvases = [canvas];
  const seen: FromWorker[] = [];
  createChartHost({
    realm: doc,
    runMode: mode,
    env: fakeEnv(),
    canvas: () => asHtml(canvas) as HTMLCanvasElement,
    replaceCanvas: () => {
      canvas = doc.createElement("canvas");
      canvases.push(canvas);
      return asHtml(canvas) as HTMLCanvasElement;
    },
    dpr: 1,
    theme: {},
    syncGroup: null,
    bench: false,
    listener: { deliver: (m) => seen.push(m), lost: noop, restored: noop, resync: noop },
  });
  const order = (): string[] =>
    seen.flatMap((m) =>
      m.t === "error" ? [m.code] : m.t === "ready" ? [`ready:${m.renderProfile}`] : [],
    );
  return { canvases, order };
}

describe("Scenario: Repeated loss gives up gracefully rather than looping (the host)", () => {
  it("inline: RESTORE_FAILED swaps the canvas and the chart comes back degraded-2d", () => {
    const { canvases, order } = mountHost("inline");
    for (let i = 0; i < 3; i += 1) frame();
    canvases[0]?.webgl2?.loseContext();
    canvases[0]?.dispatch("webglcontextlost", { preventDefault: noop });
    for (let i = 0; i < 500; i += 1) frame(); // 8 s: three tries at 1 / 2 / 4 s, then the swap
    expect(canvases).toHaveLength(2);
    expect(canvases[1]?.webgl2?.log).toEqual([]); // the new canvas never held WebGL2
    const lost = ENGINE_CONTEXT_LOST;
    const failed = ENGINE_CONTEXT_RESTORE_FAILED;
    expect(order()).toEqual(["ready:full", lost, lost, lost, failed, "ready:degraded-2d"]);
  });
});

describe("Scenario: A shader that fails to compile is a handled error (the fallback)", () => {
  const failCompile = (): void => {
    vi.spyOn(GLBackend.prototype, "submit").mockImplementation(function (this: GLBackend) {
      this.failure = {
        code: ENGINE_SHADER_COMPILE_FAILED,
        message: 'program "line" failed to compile on fake renderer: bad',
        recoverable: true,
        fallback: "degraded-2d",
      };
      return this.failure;
    });
  };

  it.each(["inline", "worker"] as RunMode[])(
    "%s: the host swaps the canvas and goes 2D",
    (mode) => {
      failCompile();
      const { canvases, order } = mountHost(mode);
      for (let i = 0; i < 10; i += 1) frame();
      expect(canvases).toHaveLength(2);
      expect(canvases[1]?.webgl2?.log).toEqual([]); // the new canvas never held WebGL2
      expect(order()).toEqual(["ready:full", ENGINE_SHADER_COMPILE_FAILED, "ready:degraded-2d"]);
    },
  );

  it("worker: the forced degraded-2d profile survives a worker restart", () => {
    failCompile();
    const { order } = mountHost("worker");
    for (let i = 0; i < 10; i += 1) frame();
    FakeWorker.created.at(-1)?.kill();
    for (let i = 0; i < 100; i += 1) frame(); // past the 1 s restart backoff
    const inits = (FakeWorker.created.at(-1)?.inbox ?? []).filter(
      (m) => (m as { t?: string }).t === "init",
    ) as { profile?: string }[];
    expect(inits.map((m) => m.profile)).toEqual(["degraded-2d"]);
    expect(order().at(-1)).toBe("ready:degraded-2d");
  });
});
