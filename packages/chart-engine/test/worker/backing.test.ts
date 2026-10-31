// E11-S10 PR 2 (README BQ-149, C-44): the 128 px growth-step policy, and the runtime drawing a
// padded backing store's exact top-left sub-rect (GL viewport + scissor, 2D clip) while the clip
// space, `frame` and the pick math keep the exact size.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Canvas2DBackend } from "../../src/canvas2d/backend.js";
import { GLBackend } from "../../src/gl/backend.js";
import type { PaneUniforms } from "../../src/viewport/index.js";
import { BACKING_STEP_PX, BackingSizer, grownPx, SETTLE_FRAMES } from "../../src/worker/backing.js";
import { rejectReason, type FromWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";

describe("Scenario: Dragging a splitter does not cause reallocation storms (policy)", () => {
  it("grows in whole 128 px steps from the current store and never shrinks", () => {
    expect(BACKING_STEP_PX).toBe(128);
    expect([grownPx(400, 400), grownPx(401, 400), grownPx(528, 400), grownPx(529, 400)]).toEqual([
      400, 528, 528, 656,
    ]);
    expect(grownPx(100, 656)).toBe(656);
  });

  it("trims to the exact size after 10 resize-free frames, not before", () => {
    const s = new BackingSizer(400, 300, 1);
    s.resize(410, 300, 1);
    expect([s.width, s.height, s.padded, s.settling]).toEqual([528, 300, true, true]);
    for (let f = 1; f < SETTLE_FRAMES; f += 1) expect(s.frame()).toBe(false);
    s.resize(405, 290, 1); // a resize restarts the count and still does not shrink
    expect([s.width, s.height]).toEqual([528, 300]);
    for (let f = 1; f < SETTLE_FRAMES; f += 1) expect(s.frame()).toBe(false);
    expect(s.frame()).toBe(true);
    expect([s.width, s.height, s.padded, s.settling, s.frame()]).toEqual([
      405,
      290,
      false,
      false,
      false,
    ]);
  });

  it("trims at once on a DPR change and on demand; a 0 size keeps the store", () => {
    const s = new BackingSizer(400, 300, 1);
    s.resize(450, 300, 1);
    s.resize(900, 600, 2);
    expect([s.width, s.height, s.settling]).toEqual([900, 600, false]);
    s.resize(950, 600, 2);
    s.resize(0, 0, 2);
    expect([s.width, s.padded, s.settling, s.trim()]).toEqual([1028, false, false, false]);
    s.resize(1100, 600, 2); // the first size after a 0 one is not a drag: exact, unpadded
    expect([s.width, s.padded]).toEqual([1100, false]);
    s.resize(1050, 600, 2);
    expect([s.trim(), s.width, s.trim()]).toEqual([true, 1050, false]);
  });

  it.each([0, 1])(
    "an unsized mount (%i px) takes its first size exactly, then grows in steps",
    (n) => {
      const s = new BackingSizer(n, n, 1);
      s.resize(300, 100, 1);
      expect([s.width, s.height, s.padded, s.settling]).toEqual([300, 100, false, false]);
      s.resize(301, 100, 1);
      expect([s.width, s.height]).toEqual([428, 100]);
    },
  );
});

describe("Scenario: a padded store is drawn in its exact sub-rect", () => {
  let out: FromWorker[];
  let rt: RenderRuntime;
  let gl: FakeGl;
  let block: () => PaneUniforms;
  const canvas = { width: 400, height: 200, getContext: () => gl };
  const frame = (): void => void vi.advanceTimersByTime(16);
  const resize = (width: number, height: number, bw?: number, bh?: number): void =>
    rt.handle({
      t: "resize",
      id: 1,
      width,
      height,
      dpr: 1,
      ...(bw !== undefined && { backingWidth: bw, backingHeight: bh }),
    });

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
    });
    [canvas.width, canvas.height] = [400, 200];
    rt.handle({
      t: "init",
      id: 1,
      canvas,
      dpr: 1,
      theme: {},
      config: { bench: true, syncGroup: null },
    });
    frame();
    block = spy.mock.calls[0]?.[0] as () => PaneUniforms;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("viewport and scissor at y = bh - h; u_viewport and the transform stay exact", () => {
    resize(410, 190, 528, 200);
    frame();
    expect([canvas.width, canvas.height]).toEqual([528, 200]);
    expect(gl.viewports.at(-1)).toEqual([0, 10, 410, 190]);
    expect([gl.scissorTest, gl.scissors.at(-1)]).toEqual([true, [0, 10, 410, 190]]);
    const f = block().floats;
    expect([f[4], f[5]]).toEqual([410, 190]);
    const last = out.filter((m) => m.t === "frame").at(-1);
    expect(last).toMatchObject({ backingStorePx: [528, 200] });
    // Within the store: no reallocation; the trim is the one more.
    resize(450, 180, 528, 200);
    frame();
    expect(rt.resizeCounters(1)?.reallocations).toBe(1);
    const enables = gl.log.filter((c) => c === "enable").length;
    expect(enables).toBe(1); // SCISSOR_TEST is switched on once, not per frame
    resize(450, 180);
    frame();
    expect([canvas.width, canvas.height, gl.scissorTest]).toEqual([450, 180, false]);
    expect(gl.viewports.at(-1)).toEqual([0, 0, 450, 180]);
    expect(rt.resizeCounters(1)?.reallocations).toBe(2);
  });

  it("rejects a store below the exact size and keeps a legal padded one", () => {
    expect(
      rejectReason({ t: "resize", id: 1, width: 10, height: 10, dpr: 2, backingWidth: 20 }),
    ).toBeNull();
    expect(
      rejectReason({ t: "resize", id: 1, width: 10, height: 10, dpr: 2, backingWidth: 19 }),
    ).toBe("malformed resize");
  });

  it("the 2D backend clips a padded store to the exact rect, and an exact one not at all", () => {
    const ctx = new FakeCtx2D();
    const backend = new Canvas2DBackend(ctx);
    backend.submit([], 0, 410, 190, 528, 200);
    expect(ctx.log.slice(0, 4)).toEqual(["save", "beginPath", "rect", "clip"]);
    expect([ctx.clips, ctx.log.at(-1)]).toEqual([["rect 0 0 410 190"], "restore"]);
    backend.submit([], 0, 410, 190);
    expect(ctx.count("clip")).toBe(1);
  });
});
