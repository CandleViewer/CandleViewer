// E11-S10 PR 1 through the runtime: u_viewport is the backing store on both axes (BQ-142), a DPR
// change resizes the backing store and tells its listeners before the next frame (BQ-152, BQ-153),
// and a 0×0 container suspends the chart and resumes it within one frame (BQ-147, BQ-148).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GLBackend } from "../../src/gl/backend.js";
import { Dirty, SceneGraph } from "../../src/scene/index.js";
import { snapHairline, type PaneUniforms } from "../../src/viewport/index.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { INPUT, rejectReason, type FromWorker } from "../../src/worker/protocol.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap } from "../interaction/fixtures.js";

let out: FromWorker[];
let rt: RenderRuntime;
let gl: FakeGl;
let canvas: { width: number; height: number; getContext(): FakeGl };
let block: () => PaneUniforms;
const frame = (): void => void vi.advanceTimersByTime(16);
const of = <T extends FromWorker["t"]>(t: T): Extract<FromWorker, { t: T }>[] =>
  out.filter((m): m is Extract<FromWorker, { t: T }> => m.t === t);
const resize = (width: number, height: number, dpr: number): void =>
  rt.handle({ t: "resize", id: 1, width, height, dpr });

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  gl = new FakeGl({ params: ROOMY });
  const spy = vi.spyOn(GLBackend.prototype, "setPaneUniforms");
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: minuteMap(),
  });
  canvas = { width: 400, height: 200, getContext: () => gl };
  const config = { bench: true, syncGroup: null };
  rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config });
  frame();
  block = spy.mock.calls[0]?.[0] as () => PaneUniforms;
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("Scenario: Hairlines are crisp at fractional DPI", () => {
  it("u_viewport is the backing store on both axes, not height * dpr (BQ-142 regression)", () => {
    resize(400.8, 200.4, 1.25); // backing 501 × 251; height * dpr is 250.5
    frame();
    const f = block().floats;
    expect([f[4], f[5]]).toEqual([canvas.width, canvas.height]);
    expect([canvas.width, canvas.height]).toEqual([501, 251]);
    // The line shader's p / u_viewport * backing: a snapped hairline stays on a pixel centre.
    for (const y of [0.3, 17.9, 100, 199.6]) {
      const device = ((snapHairline(y, 1.25) * 1.25) / (f[5] as number)) * canvas.height;
      expect(device - Math.floor(device)).toBeCloseTo(0.5, 9);
    }
  });

  it("sizes the backing store as round(css * dpr) and reports it on `frame`", () => {
    resize(320, 180, 1.25);
    frame();
    expect(of("frame").at(-1)).toMatchObject({ dpr: 1.25, backingStorePx: [400, 225] });
  });
});

describe("Scenario: Moving to a different-DPI monitor re-renders correctly", () => {
  it("resizes the backing store, fires dprChanged(1, 2) once before the next frame", () => {
    const seen: unknown[] = [];
    rt.onDprChange(1, (from, to) => {
      seen.push([from, to, canvas.width, canvas.height, of("frame").length]);
    });
    const framesBefore = of("frame").length;
    resize(400, 200, 2);
    resize(400, 200, 2); // the same ratio again: no second notice, no reallocation
    expect(seen).toEqual([[1, 2, 800, 400, framesBefore]]);
    frame();
    expect(of("frame").at(-1)).toMatchObject({ dpr: 2, backingStorePx: [800, 400] });
    expect(rt.resizeCounters(1)).toEqual({ reallocations: 1, dprChanges: 1, lastDpr: 2 });
  });

  it("a DPR change at the same CSS size still marks every pane LAYOUT and STYLE", () => {
    const marked = vi.spyOn(SceneGraph.prototype, "markResize");
    resize(400, 200, 1); // the same size and ratio: nothing to mark
    expect(marked).not.toHaveBeenCalled();
    resize(400, 200, 2); // the layout engine's setSize short-circuits; the DPR branch marks
    expect(marked.mock.calls).toEqual([[]]); // every pane, not one
    const graph = marked.mock.contexts[0] as SceneGraph;
    for (const id of ["main", "main/price-axis", "chart/time-axis"]) {
      expect(graph.get(id)?.dirty ?? 0, id).toSatisfy((d: number) => (d & Dirty.LAYOUT) !== 0);
    }
    for (const id of ["main/price-axis", "chart/time-axis"]) {
      expect(graph.get(id)?.dirty ?? 0, id).toSatisfy((d: number) => (d & Dirty.STYLE) !== 0);
    }
  });

  it("a throwing listener posts a recoverable error; the others run and the resize lands", () => {
    const after = vi.fn();
    rt.onDprChange(1, () => {
      throw new Error("atlas");
    });
    rt.onDprChange(1, after);
    resize(400, 200, 2);
    expect(after).toHaveBeenCalledWith(1, 2);
    expect(of("error").at(-1)).toMatchObject({ id: 1, message: "atlas", recoverable: true });
    frame();
    expect(of("frame").at(-1)).toMatchObject({ dpr: 2, backingStorePx: [800, 400] });
  });

  it("unsubscribes, and knows no listener or counters for an unknown chart", () => {
    const cb = vi.fn();
    const off = rt.onDprChange(1, cb);
    off?.();
    resize(400, 200, 3);
    expect(cb).not.toHaveBeenCalled();
    expect(rt.onDprChange(9, cb)).toBeUndefined();
    expect(rt.resizeCounters(9)).toBeUndefined();
  });
});

describe("Scenario: A zero-size container does not crash or burn CPU", () => {
  it("a 0×0 resize is legal; NaN, negative sizes and dpr 0 are not (C-45)", () => {
    expect(rejectReason({ t: "resize", id: 1, width: 0, height: 0, dpr: 1 })).toBeNull();
    expect(rejectReason({ t: "resize", id: 1, width: 0, height: -1, dpr: 1 })).toBe(
      "malformed resize",
    );
  });

  it("suspends: no error, no allocation, no frame; data still acks; export says suspended", async () => {
    resize(0, 0, 1);
    const calls = gl.log.length;
    const frames = of("frame").length;
    for (let i = 0; i < 10; i += 1) {
      rt.handle({
        t: "input",
        id: 1,
        kind: "pointer",
        events: new Float32Array([INPUT.move, 5, 5, 0, 0, 0]),
      });
      frame();
    }
    const layout = { count: 0, columns: [], params: [] };
    rt.handle({
      t: "data",
      id: 1,
      store: "bars",
      op: "append",
      layout,
      buffer: new ArrayBuffer(0),
    });
    expect(gl.log.length).toBe(calls); // no GL call at all while suspended
    rt.handle({ t: "command", id: 1, cmd: { k: "export", reqId: 4 } });
    await Promise.resolve();
    expect(of("error")).toEqual([]);
    expect([canvas.width, canvas.height]).toEqual([400, 200]);
    expect(of("frame").length).toBe(frames);
    expect(of("ack")).toHaveLength(1);
    expect(of("exported")).toEqual([
      { t: "exported", id: 1, reqId: 4, blob: null, reason: "suspended" },
    ]);
  });

  it("resumes with a correct frame within one frame of regaining size", () => {
    resize(0, 120, 1); // one axis at 0 is enough
    frame();
    const frames = of("frame").length;
    resize(300, 120, 1);
    frame();
    expect(of("frame").slice(frames)).toEqual([
      expect.objectContaining({ dpr: 1, backingStorePx: [300, 120] }),
    ]);
  });
});

describe("BQ-157: a resize never moves the cursor", () => {
  it("a resize and a DPR change post no new cursor summary", () => {
    rt.handle({
      t: "input",
      id: 1,
      kind: "pointer",
      events: new Float32Array([INPUT.move, 50, 5, 0, 0, 0]),
    });
    frame();
    const summaries = of("a11y").length;
    expect(summaries).toBeGreaterThan(0);
    resize(500, 250, 1);
    frame();
    resize(500, 250, 2);
    frame();
    expect(of("a11y")).toHaveLength(summaries);
  });
});

describe("E11-T08 goldens (BQ-155, G-30): SwiftShader, wait on #391", () => {
  it.todo("grid, axis rule and crosshair at dpr 1 match the reference at <= 0.1 % difference");
  it.todo("grid, axis rule and crosshair at dpr 1.25 match the reference at <= 0.1 % difference");
  it.todo("grid, axis rule and crosshair at dpr 2 match the reference at <= 0.1 % difference");
  it.todo("Scenario: Heatmap layer is capped at 2x: textures at ratio 2 under dpr 3, <= 20 MB");
});
