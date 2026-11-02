// E11-T05 PR 1: degraded-2d through the runtime. S1 (no WebGL2, or the forced profile: 2D ops,
// no throw), S3 (one input script, fake GL vs fake 2D: equal viewport, pick and a11y messages),
// the capability vocabulary on ENGINE_NO_WEBGL2 (BQ-89/90), F-13's refused export (BQ-92), the
// re-probe (BQ-93), the test-only force hook (BQ-94) and `frame`'s runMode (BQ-97).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, setHostEnvFactory } from "../../src/api/chart.js";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import { GLBackend } from "../../src/gl/backend.js";
import {
  FAILED_CONTEXT_REASON,
  REDUCED_CAPABILITIES,
  reducedCapabilities,
  selectProfile,
  type CapabilityReport,
} from "../../src/gl/capability.js";
import { probeRenderProfile } from "../../src/host/mount.js";
import { createChartHost } from "../../src/worker/host.js";
import {
  BACKGROUND_TOKEN,
  ENGINE_EXPORT_UNAVAILABLE,
  ENGINE_NO_WEBGL2,
  ENGINE_SHADER_COMPILE_FAILED,
  ExportUnavailableError,
  INPUT,
  KEY,
  type FromWorker,
  type RunMode,
} from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { asHtml, canvasIn, fakeContainer, FakeDocument } from "../api/fake-dom.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { fakeEnv, FakeWorker } from "./fake-worker.js";

type Listener = (ev: { preventDefault(): void }) => void;

/** A canvas whose `getContext("webgl2")` answers `gl` (null: stubbed off) and "2d" a fake. */
function surface(gl: FakeGl | null) {
  const ctx = new FakeCtx2D();
  const asked: string[] = [];
  const on = new Map<string, Listener>();
  return {
    width: 200,
    height: 100,
    ctx,
    asked,
    getContext: (id: string): unknown => (asked.push(id), id === "webgl2" ? gl : ctx),
    addEventListener: (type: string, cb: Listener) => void on.set(type, cb),
    removeEventListener: (type: string) => void on.delete(type),
    fire: (type: string) => on.get(type)?.({ preventDefault: () => undefined }),
    convertToBlob: (): Promise<unknown> => Promise.resolve({ png: true }),
  };
}

let out: FromWorker[];
let rt: RenderRuntime;
const frame = (): void => void vi.advanceTimersByTime(16);

function runtime(probe: CapabilityReport = FULL, runMode: RunMode = "inline"): void {
  out = [];
  rt = createRenderRuntime({
    runMode,
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Date.now(),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => probe,
  });
}

function init(canvas: object, profile?: "degraded-2d", id = 1): void {
  rt.handle({
    t: "init",
    id,
    canvas,
    dpr: 1,
    theme: { [BACKGROUND_TOKEN]: "#0b0e11" },
    config: { bench: true, syncGroup: null },
    ...(profile && { profile }),
  });
}

const noWebgl2 = (): Extract<FromWorker, { t: "error" }>[] =>
  out.flatMap((m) => (m.t === "error" && m.code === ENGINE_NO_WEBGL2 ? [m] : []));

beforeEach(() => {
  vi.useFakeTimers();
  runtime();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  setHostEnvFactory(null);
});

describe("Scenario: No WebGL2 degrades instead of failing (S1)", () => {
  it("a stubbed getContext('webgl2') → null draws through Canvas 2D, names the reduction, never throws", () => {
    const submit = vi.spyOn(Canvas2DBackend.prototype, "submit");
    const c = surface(null);
    init(c);
    expect(() => frame()).not.toThrow();
    expect(submit).toHaveBeenCalled();
    expect(c.ctx.fills).toEqual(["#0b0e11"]); // painted, not a blank canvas
    expect(out.find((m) => m.t === "ready")).toMatchObject({ renderProfile: "degraded-2d" });
    expect(noWebgl2()).toEqual([
      expect.objectContaining({
        recoverable: true,
        details: { reducedCapabilities: [...REDUCED_CAPABILITIES], reason: "no-webgl2" },
      }),
    ]);
  });

  it("a probe that saw no WebGL2, or a failed context, says which as a code (BQ-89)", () => {
    runtime(selectProfile(null));
    init(surface(new FakeGl({ params: ROOMY })));
    frame();
    runtime(selectProfile(null, FAILED_CONTEXT_REASON));
    const c = surface(new FakeGl({ params: ROOMY }));
    init(c);
    frame();
    expect(c.asked).toEqual(["2d"]); // the probe said no: WebGL2 is not even asked for
    expect(noWebgl2()[0]?.details).toMatchObject({ reason: "context-failed" });
    expect(noWebgl2()[0]?.message).toBe(FAILED_CONTEXT_REASON);
  });

  it("the forced profile (the handoff and the BQ-94 hook) paints 2D without re-announcing", () => {
    const c = surface(new FakeGl({ params: ROOMY }));
    init(c, "degraded-2d");
    frame();
    expect([c.asked, c.ctx.fills, noWebgl2()]).toEqual([["2d"], ["#0b0e11"], []]);
  });

  it.each(["inline", "worker"] as RunMode[])(
    "%s: frame keeps runMode and renderProfile under degraded-2d (BQ-97)",
    (mode) => {
      runtime(FULL, mode);
      init(surface(null));
      frame();
      const f = out.find((m) => m.t === "frame");
      expect(f).toMatchObject({ runMode: mode, renderProfile: "degraded-2d", drawCalls: 0 });
    },
  );

  it("maps profiles to the five capabilities: all under degraded-2d, none otherwise", () => {
    expect(reducedCapabilities("degraded-2d")).toEqual(REDUCED_CAPABILITIES);
    expect([reducedCapabilities("full"), reducedCapabilities("reduced")]).toEqual([[], []]);
  });
});

describe("Scenario: The backend swap is invisible to the rest of the engine (S3)", () => {
  const row = (type: number, x: number, buttons = 0): Float32Array =>
    new Float32Array([type, x, 0, buttons, 0, 0]);

  /** One scripted session; the viewport, pick and a11y messages it produced. */
  function script(gl: FakeGl | null): FromWorker[] {
    runtime();
    init(surface(gl));
    frame();
    rt.handle({ t: "command", id: 1, cmd: { k: "setViewport", timeStart: 0, timeEnd: 6e9 } });
    frame();
    for (const [type, x, b] of [
      [INPUT.down, 50, 1],
      [INPUT.move, 140, 1],
      [INPUT.up, 140, 0],
      [INPUT.wheel, 100, 120],
      [INPUT.key, KEY.zoomIn, 0],
      [INPUT.move, 75, 0],
    ] as const) {
      rt.handle({ t: "input", id: 1, kind: "pointer", events: row(type, x, b) });
      frame();
    }
    rt.handle({ t: "command", id: 1, cmd: { k: "pickAt", x: 75, y: 40 } });
    rt.handle({ t: "resize", id: 1, width: 180, height: 90, dpr: 2 });
    frame();
    return out.filter((m) => m.t === "viewport" || m.t === "pick" || m.t === "a11y");
  }

  it("the same input script on fake GL and fake 2D gives equal viewport, pick and a11y", () => {
    const gl = script(new FakeGl({ params: ROOMY }));
    const twoD = script(null);
    expect(gl.length).toBeGreaterThan(4);
    expect(twoD).toEqual(gl);
  });
});

describe("ChartEvents.error carries the optional details (BQ-90)", () => {
  it("ENGINE_NO_WEBGL2 reaches the app with its codes, as a copy of the engine's list", () => {
    const container = fakeContainer(200, 100);
    container.ownerDocument.webgl2Available = false;
    const theme = { palette: "default", convention: "standard", colors: {} } as const;
    const chart = createChart({ container: asHtml(container), theme });
    const seen: { details?: unknown }[] = [];
    chart.subscribe("error", (e) => seen.push(e));
    frame();
    expect(seen).toEqual([
      expect.objectContaining({
        code: ENGINE_NO_WEBGL2,
        details: { reducedCapabilities: [...REDUCED_CAPABILITIES], reason: "no-webgl2" },
      }),
    ]);
    const details = seen[0]?.details as { reducedCapabilities: unknown };
    expect(details.reducedCapabilities).not.toBe(REDUCED_CAPABILITIES); // the engine's list stays
    chart.dispose();
  });
});

describe("F-13: an export is refused, never stale, while parked or failed (BQ-92)", () => {
  it("mid-loss: exported { blob: null, reason: context-lost }; after giving up: backend-failed", async () => {
    const gl = new FakeGl({ params: ROOMY });
    const c = surface(gl);
    init(c);
    frame();
    gl.loseContext();
    c.fire("webglcontextlost");
    rt.handle({ t: "command", id: 1, cmd: { k: "export", reqId: 1 } });
    vi.advanceTimersByTime(8000); // three failed tries at 1 / 2 / 4 s: gave up
    rt.handle({ t: "command", id: 1, cmd: { k: "export", reqId: 2 } });
    await vi.runAllTimersAsync();
    const exported = out.flatMap((m) => (m.t === "exported" ? [[m.reqId, m.blob, m.reason]] : []));
    expect(exported).toEqual([
      [1, null, "context-lost"],
      [2, null, "backend-failed"],
    ]);
  });

  it("a context lost before its event is dispatched refuses on the driver's truth (context-lost)", async () => {
    const gl = new FakeGl({ params: ROOMY });
    init(surface(gl));
    frame();
    gl.loseContext(); // no webglcontextlost yet: the loss phase is still live
    rt.handle({ t: "command", id: 1, cmd: { k: "export", reqId: 1 } });
    await vi.runAllTimersAsync();
    const exported = out.flatMap((m) => (m.t === "exported" ? [[m.reqId, m.blob, m.reason]] : []));
    expect(exported).toEqual([[1, null, "context-lost"]]);
  });

  it("a failed compile refuses; a healthy degraded-2d chart draws first, then encodes", async () => {
    vi.spyOn(GLBackend.prototype, "submit").mockImplementation(function (this: GLBackend) {
      this.failure = {
        code: ENGINE_SHADER_COMPILE_FAILED,
        message: "m",
        recoverable: true,
        fallback: "degraded-2d",
      };
      return this.failure;
    });
    init(surface(new FakeGl({ params: ROOMY })));
    frame();
    const c = surface(null);
    init(c, "degraded-2d", 2);
    frame();
    const painted = c.ctx.count("fillRect");
    rt.handle({ t: "command", id: 1, cmd: { k: "export", reqId: 1 } });
    rt.handle({ t: "command", id: 2, cmd: { k: "export", reqId: 2 } });
    expect(c.ctx.count("fillRect")).toBe(painted + 1); // drawn in the encoding task
    await vi.runAllTimersAsync();
    const exported = out.flatMap((m) => (m.t === "exported" ? [[m.reqId, m.blob, m.reason]] : []));
    expect(exported).toEqual([
      [1, null, "backend-failed"],
      [2, { png: true }, undefined],
    ]);
  });

  it("takeScreenshot rejects with the distinct ExportUnavailableError while parked", async () => {
    const container = fakeContainer(200, 100);
    const theme = { palette: "default", convention: "standard", colors: {} } as const;
    const chart = createChart({ container: asHtml(container), theme });
    frame();
    const canvas = canvasIn(container);
    canvas?.webgl2?.loseContext();
    canvas?.dispatch("webglcontextlost", { preventDefault: () => undefined });
    const shot = chart.takeScreenshot();
    await expect(shot).rejects.toBeInstanceOf(ExportUnavailableError);
    await expect(shot).rejects.toMatchObject({
      code: ENGINE_EXPORT_UNAVAILABLE,
      reason: "context-lost",
    });
    chart.dispose();
  });
});

describe("the host's side (BQ-93, BQ-94)", () => {
  it("re-probes after a failed probe, so inline Retry WebGL2 can succeed (BQ-93)", () => {
    const doc = new FakeDocument();
    doc.webgl2Available = false;
    const html = doc as unknown as Document;
    expect(probeRenderProfile(html).profile).toBe("degraded-2d");
    doc.webgl2Available = true;
    const ok = probeRenderProfile(html);
    expect(ok.caps).not.toBeNull();
    expect(probeRenderProfile(html)).toBe(ok); // a success is cached
  });

  it.each(["inline", "worker"] as RunMode[])(
    "%s: the test-only forceProfile hook inits every chart forced to 2D (BQ-94)",
    (mode) => {
      const doc = new FakeDocument();
      doc.offscreenAvailable = mode === "worker";
      doc.defaultView = { devicePixelRatio: 1, OffscreenCanvas: class {} };
      const canvas = doc.createElement("canvas");
      const seen: FromWorker[] = [];
      const noop = (): void => undefined;
      const host = createChartHost({
        realm: doc,
        runMode: mode,
        env: fakeEnv({ forceProfile: "degraded-2d" }),
        canvas: () => asHtml(canvas) as HTMLCanvasElement,
        replaceCanvas: () => asHtml(canvas) as HTMLCanvasElement,
        dpr: 1,
        theme: {},
        syncGroup: null,
        bench: false,
        listener: { deliver: (m) => seen.push(m), lost: noop, restored: noop, resync: noop },
      });
      for (let i = 0; i < 3; i += 1) frame();
      if (mode === "inline") {
        expect(seen.find((m) => m.t === "ready")).toMatchObject({ renderProfile: "degraded-2d" });
      } else {
        const inits = (FakeWorker.created.at(-1)?.inbox ?? []).filter(
          (m) => (m as { t?: string }).t === "init",
        ) as { profile?: string }[];
        expect(inits.map((m) => m.profile)).toEqual(["degraded-2d"]);
      }
      host.dispose();
    },
  );
});
