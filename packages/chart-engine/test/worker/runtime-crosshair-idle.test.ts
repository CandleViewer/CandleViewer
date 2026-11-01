// E11-S07 perf fix pins (resize-drag regression on #388): an idle crosshair costs O(1) a frame
// (no line rewrite, nothing published), the node joins the scene graph on its first lines only,
// and that lazy join survives a context loss and a degraded-2d re-init, for a local cursor and a
// held remote line alike.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CROSSHAIR_NODE_ID, CrosshairNode } from "../../src/overlays/crosshair-node.js";
import { SceneGraph } from "../../src/scene/graph.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import {
  BACKGROUND_TOKEN,
  ENGINE_CONTEXT_RESTORED,
  INPUT,
  type FromWorker,
  type ToWorker,
} from "../../src/worker/protocol.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { lossCanvas, roomyGl } from "../chaos/harness.js";
import { FULL } from "../gl/fake-gl.js";
import { MIN_US, T0, timeMap } from "../overlays/fixture.js";

const THEME = { [BACKGROUND_TOKEN]: "#000000", "color.crosshair": "#ff0000" };
const RED = "rgba(255, 0, 0, 1)";
const MUTED = `rgba(255, 0, 0, ${Math.round(Math.fround(0.7) * 255) / 255})`;

let out: FromWorker[];
let rt: RenderRuntime;
const frame = (n = 1): void => void vi.advanceTimersByTime(16 * n);
const of = <T extends FromWorker["t"]>(t: T, id = 1): Extract<FromWorker, { t: T }>[] =>
  out.filter((m): m is Extract<FromWorker, { t: T }> => m.t === t && m.id === id);

function init(id: number, canvas: object, syncGroup: string | null = null, bench = false): void {
  rt.handle({
    t: "init",
    id,
    canvas,
    dpr: 1,
    theme: THEME,
    config: { bench, syncGroup },
  } satisfies ToWorker);
}

const ctx2d = (): { width: number; height: number; ctx: FakeCtx2D; getContext(): FakeCtx2D } => {
  const ctx = new FakeCtx2D();
  return { width: 464, height: 300, ctx, getContext: () => ctx };
};
const move = (x: number, y: number, id = 1): void =>
  rt.handle({
    t: "input",
    id,
    kind: "pointer",
    events: new Float32Array([INPUT.move, x, y, 0, 0, 0]),
  });
const view = (id = 1): void =>
  rt.handle({
    t: "command",
    id,
    cmd: { k: "setViewport", timeStart: T0 + 10 * MIN_US, timeEnd: T0 + 30 * MIN_US },
  });
const strokes = (ctx: FakeCtx2D, from: number, style: string): number =>
  ctx.paths.slice(from).filter((p) => p.op === "stroke" && p.style === style).length;

/** Every scene graph the runtime builds, in creation order (one per `init`). */
function graphs(): SceneGraph[] {
  const spy = vi.spyOn(SceneGraph.prototype, "addPane");
  return spy.mock.contexts as SceneGraph[];
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  out = [];
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: timeMap(50),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("idle: O(1), no rewrite, nothing published", () => {
  it("test_idle_noPointerNoRemote_resizeAndPanFrames_neverWriteTheLines_norPublish", () => {
    const write = vi.spyOn(CrosshairNode.prototype, "write");
    init(1, ctx2d(), "g", true);
    init(2, ctx2d(), "g", true); // a peer: a publish would hand it a remote line, so a frame
    frame(4);
    out.length = 0;
    for (let i = 0; i < 20; i += 1) {
      rt.handle({ t: "resize", id: 1, width: 300 + i * 3, height: 200, dpr: 1 });
      view();
      frame();
    }
    expect(of("frame", 1).length).toBeGreaterThanOrEqual(20); // chart 1 drew every frame
    expect(write).not.toHaveBeenCalled(); // the idle exit: no signature compare at all
    expect(of("frame", 2)).toEqual([]); // `published` stayed NaN: the peer never woke
    expect(of("crosshair", 1)).toEqual([]);
  });
});

describe("lazy join: the node enters the graph with its first lines", () => {
  it("test_lazyJoin_neverCrossedChart_hasNoNodeInTheWalk_firstLinesJoin", () => {
    const made = graphs();
    init(1, ctx2d());
    view();
    frame(4);
    const g = made[0] as SceneGraph;
    expect(g.get(CROSSHAIR_NODE_ID)).toBeUndefined();
    expect(g.walk().some((n) => n.id === CROSSHAIR_NODE_ID)).toBe(false);
    move(100, 80);
    frame();
    expect(g.get(CROSSHAIR_NODE_ID)).toBeInstanceOf(CrosshairNode);
    expect(g.walk().some((n) => n.id === CROSSHAIR_NODE_ID)).toBe(true);
  });
});

describe("the lazy join across a context loss and a degraded-2d re-init", () => {
  it("test_contextLossAndRestore_neverShownNode_firstMoveDrawsInThatFrame", () => {
    const gl = roomyGl();
    const c = lossCanvas(gl);
    init(1, c);
    view();
    frame(4);
    c.lose();
    frame(2);
    c.restore();
    frame(80); // inside attempt 1's wait: restored and framed
    expect(of("error").map((e) => e.code)).toContain(ENGINE_CONTEXT_RESTORED);
    const mark = gl.log.length;
    move(100, 40);
    frame();
    expect(of("crosshair").at(-1)?.visible).toBe(true);
    expect(gl.log.slice(mark).filter((x) => x === "drawArraysInstanced")).toHaveLength(1);
  });

  it("test_degraded2dReinit_neverShownNode_firstMoveDrawsInThatFrame", () => {
    init(1, ctx2d());
    view();
    frame(4);
    const fresh = ctx2d();
    init(1, fresh); // the handoff's second init: a new canvas and scene
    view();
    frame(4);
    expect(strokes(fresh.ctx, 0, RED)).toBe(0);
    move(100, 80);
    frame();
    expect(strokes(fresh.ctx, 0, RED)).toBeGreaterThan(0);
  });

  it("test_degraded2dReinit_heldRemoteLine_rejoinsOnItsFirstDraw", () => {
    const made = graphs();
    init(1, ctx2d(), "g");
    view();
    rt.handle({
      t: "sync",
      groupId: "g",
      timeRange: [T0 + 10 * MIN_US, T0 + 30 * MIN_US],
      crosshair: T0 + 15 * MIN_US,
    });
    frame(4);
    const fresh = ctx2d();
    init(1, fresh, "g"); // the remote line is held across the re-init
    view();
    const g = made[1] as SceneGraph;
    expect(g.get(CROSSHAIR_NODE_ID)).toBeUndefined();
    frame();
    expect(g.get(CROSSHAIR_NODE_ID)).toBeInstanceOf(CrosshairNode);
    expect(strokes(fresh.ctx, 0, MUTED)).toBeGreaterThan(0); // drawn in that first frame
  });
});
