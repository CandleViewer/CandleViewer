// E14-T03 PR 2 through the runtime: Scenario 4 (WebGL2 unavailable: the drawings' lines, fills and
// labels still draw, in Canvas 2D, beside the one `ENGINE_NO_WEBGL2` notice the app shows as its
// "Basic rendering" badge, E11-D04 D13 / E11-D02 D16; drawings are not among `reducedCapabilities`)
// and the `engine_drawing_*` block on the `frame` message (the engine's stats channel).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { REDUCED_CAPABILITIES } from "../../src/gl/capability.js";
import type { DrawingInput } from "../../src/layers/drawings/model.js";
import { type Command, ENGINE_NO_WEBGL2, type FromWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap } from "../interaction/fixtures.js";
import { DashCtx } from "../layers/drawings/harness.js";

type Frame = Extract<FromWorker, { t: "frame" }>;
const T = (i: number): number => minuteMap().indexToTime(i);
const style = { colour: 0x2962ffff, fill: 0x2962ff33, width: 2, dash: 1 } as const;
const DRAWINGS: DrawingInput[] = [
  { id: "a", kind: "segment", points: [T(10), 100, T(15), 150], style, label: "trend" },
  { id: "b", kind: "rect", points: [T(20), 110, T(30), 140], style, label: "zone" },
  { id: "c", kind: "text", points: [T(40), 120], style, label: "note" },
];

let out: FromWorker[];
let rt: RenderRuntime;
let ctx2d: DashCtx;
const frame = (): void => void vi.advanceTimersByTime(16);
const cmd = (c: object): void => rt.handle({ t: "command", id: 1, cmd: c as Command });
const frames = (): Frame[] => out.filter((m): m is Frame => m.t === "frame");

/** `webgl2`: a GL fake, or null (the canvas refuses it after a good probe: no WebGL2). */
function start(webgl2: boolean): void {
  ctx2d = new DashCtx();
  const getContext = (id: string): unknown =>
    id === "2d" ? ctx2d : webgl2 ? new FakeGl({ params: ROOMY }) : null;
  const canvas = { width: 800, height: 600, getContext };
  const config = { bench: true, syncGroup: null };
  rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config });
  frame();
}

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: minuteMap(),
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Scenario: WebGL2 unavailable", () => {
  it("lines, fills and labels draw in 2D with one capability notice, not a blank layer", () => {
    start(false);
    cmd({ k: "setDrawings", op: "replace", drawings: DRAWINGS });
    cmd({ k: "setViewport", timeStart: T(0), timeEnd: T(60) });
    frame();
    const notices = out.filter((m) => m.t === "error");
    expect(notices).toEqual([
      expect.objectContaining({
        code: ENGINE_NO_WEBGL2,
        recoverable: true,
        details: { reducedCapabilities: [...REDUCED_CAPABILITIES], reason: "no-webgl2" },
      }),
    ]);
    expect(frames().at(-1)?.renderProfile).toBe("degraded-2d");
    // The segment and the rect's four edges stroke dashed; the rect's fill fills; three labels.
    const strokes = ctx2d.paths.filter((p) => p.op === "stroke");
    const segments = strokes.flatMap((p) => p.parts.filter((s) => s.startsWith("moveTo")));
    expect(segments).toHaveLength(1 + 4);
    expect(ctx2d.paths.filter((p) => p.op === "fill" && p.style.startsWith("rgba"))).toHaveLength(
      1,
    );
    expect(ctx2d.texts.map(([text]) => text)).toEqual(["trend", "zone", "note"]);
    frame();
    expect(out.filter((m) => m.t === "error")).toHaveLength(1); // said once
  });
});

describe("engine_drawing_* on the frame message", () => {
  const last = (): Frame => frames().at(-1) as Frame;

  it("no drawings, no block; then the count, uploads, the label draw and the layer time", () => {
    start(true);
    expect(last().drawings).toBeUndefined();
    cmd({ k: "setDrawings", op: "replace", drawings: DRAWINGS });
    frame();
    // Lines: the segment and 4 rect edges; fills: the rect; glyphs: "trend", "zone", "note".
    const uploads = 5 + 1 + 13;
    expect(last().drawings).toEqual({
      count: 3,
      layerFrameMs: 0, // the fake clock does not move inside a frame
      instanceUploads: uploads,
      textDrawCalls: 1,
      tokenFallbacks: 0,
      missingToken: null,
    });
    cmd({ k: "setViewport", timeStart: T(5), timeEnd: T(70) }); // a pan: no upload
    frame();
    expect(last().drawings?.instanceUploads).toBe(uploads);
    cmd({ k: "setDrawings", op: "patch", drawings: [{ ...DRAWINGS[2], points: [T(41), 121] }] });
    frame();
    expect(last().drawings?.instanceUploads).toBe(uploads + 4); // "note"'s 4 glyphs moved
  });

  it("counts a theme token the theme lacks (the warn names it), and stops once it is there", () => {
    start(true);
    const token = { ...style, colour: "color.drawing.missing" };
    cmd({ k: "setDrawings", op: "replace", drawings: [{ ...DRAWINGS[0], style: token }] });
    frame();
    expect(last().drawings).toMatchObject({
      tokenFallbacks: 1,
      missingToken: "color.drawing.missing",
    });
    cmd({ k: "setTheme", theme: { "color.drawing.missing": "#00ff00" } });
    frame();
    expect(last().drawings?.tokenFallbacks).toBe(1);
  });
});
