// E11-S04 PR 1 through the runtime: the viewport is the layout's plot rect (RULED (5)), a drag
// coasts on the chart's frame scheduler, and every cancel reason ends the glide. Bars come from
// the test-only `RuntimeDeps.timeMap` seam (BQ-111); frames and time are driven by hand.
import { beforeEach, describe, expect, it } from "vitest";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { MOD } from "../../src/interaction/wheel.js";
import { BACKGROUND_TOKEN, INPUT, KEY, type FromWorker } from "../../src/worker/protocol.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FULL } from "../gl/fake-gl.js";
import { AT_14, MIN, minuteMap, rows } from "../interaction/fixtures.js";

let out: FromWorker[];
let pending: (() => void)[];
let now: number;
let rt: RenderRuntime;

const frame = (n = 1): void => {
  for (let i = 0; i < n; i += 1) {
    now += 16;
    for (const cb of pending.splice(0)) cb();
  }
};
const viewports = (): Extract<FromWorker, { t: "viewport" }>[] =>
  out.filter((m): m is Extract<FromWorker, { t: "viewport" }> => m.t === "viewport");

function make(
  width: number,
  height: number,
  syncGroup: string | null = null,
  reduce = false,
): void {
  const ctx = new FakeCtx2D();
  rt.handle({
    t: "init",
    id: 1,
    canvas: { width, height, getContext: () => ctx },
    dpr: 1,
    theme: { [BACKGROUND_TOKEN]: "#000000" },
    config: { bench: false, syncGroup },
    ...(reduce && { reducedMotion: true }),
  });
  rt.handle({
    t: "command",
    id: 1,
    cmd: { k: "setViewport", timeStart: AT_14 - 100 * MIN, timeEnd: AT_14 + 25 * MIN },
  });
  frame();
}

const input = (kind: "pointer" | "wheel" | "key", ...r: number[][]): void =>
  rt.handle({ t: "input", id: 1, kind, events: rows(...r) });

/** A 2 px/ms flick right, released while moving: the glide starts. */
function flick(): void {
  input("pointer", [INPUT.down, 308, 300, 1, 0, 0]);
  for (let x = 324; x <= 500; x += 16) input("pointer", [INPUT.move, x, 300, 1, 0, 8]);
  input("pointer", [INPUT.up, 500, 300, 0, 0, 8]);
}

beforeEach(() => {
  out = [];
  pending = [];
  now = 1000;
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void pending.push(cb),
    now: () => now,
    setTimer: () => undefined,
    probe: () => FULL,
    timeMap: minuteMap(),
  });
});

describe("the viewport is the layout's plot rect (BQ-101, RULED (5))", () => {
  it("spans 1216 px of a 1280 px canvas, and the wheel anchors at the true plot x", () => {
    make(1280, 744);
    const v = viewports().at(-1);
    if (v === undefined) throw new Error("no viewport");
    // The visible span over the spacing is the plot's width, not the canvas's.
    expect(((v.timeEnd - v.timeStart) / MIN) * v.barSpacing).toBeCloseTo(1216, 6);
    const at = (x: number, w: typeof v): number => w.timeStart + (x / w.barSpacing) * MIN;
    input("wheel", [INPUT.wheel, 1210, 300, -100, 0, 0]); // a notch near the plot's right edge
    frame();
    const z = viewports().at(-1);
    if (z === undefined) throw new Error("no viewport");
    expect(z.barSpacing).toBeGreaterThan(v.barSpacing);
    expect(Math.abs(at(1210, z) - at(1210, v)) / MIN).toBeLessThan(0.5 / z.barSpacing);
    input("wheel", [INPUT.wheel, 1250, 300, -100, 0, 0]); // over the price axis: inert (G-5)
    frame();
    expect(viewports().at(-1)).toEqual(z);
  });
});

describe("drag and coast through the runtime (BQ-103)", () => {
  it("a flick keeps posting viewports while it glides, then parks", () => {
    make(1064, 624);
    flick();
    frame();
    const released = viewports().length;
    frame(5);
    expect(viewports().length).toBe(released + 5); // one viewport a frame while gliding
    frame(100);
    const rested = viewports().length;
    frame(5);
    expect([viewports().length, pending.length]).toEqual([rested, 0]); // at rest and parked
  });

  it.each([
    [
      "setViewport",
      (): void =>
        rt.handle({
          t: "command",
          id: 1,
          cmd: { k: "setViewport", timeStart: AT_14 - 100 * MIN, timeEnd: AT_14 },
        }),
    ],
    [
      "sync",
      (): void =>
        rt.handle({
          t: "sync",
          groupId: "g",
          timeRange: [AT_14 - 100 * MIN, AT_14],
          crosshair: null,
        }),
    ],
    ["resize", (): void => rt.handle({ t: "resize", id: 1, width: 1000, height: 600, dpr: 1 })],
  ])("%s ends the glide where it is", (_, cancel) => {
    make(1064, 624, "g");
    flick();
    frame(2);
    cancel();
    frame();
    const after = viewports().length;
    frame(5);
    expect(viewports().length).toBe(after); // no glide frame after the cancel
  });
});

describe("Scenario: Every pointer gesture has a keyboard equivalent (worker key rows)", () => {
  const last = (): Extract<FromWorker, { t: "viewport" }> => {
    const v = viewports().at(-1);
    if (v === undefined) throw new Error("no viewport");
    return v;
  };
  const press = (code: number, mods = 0): Extract<FromWorker, { t: "viewport" }> => {
    input("key", [INPUT.key, code, 0, 0, mods, 0]);
    frame();
    return last();
  };

  it("←, Shift+→, Home, End, +, − and Ctrl+Home each post one viewport", () => {
    make(1064, 624);
    const v0 = last();
    expect((press(KEY.left).timeStart - v0.timeStart) / MIN).toBeCloseTo(-1, 6);
    expect((press(KEY.right, MOD.shift).timeStart - v0.timeStart) / MIN).toBeCloseTo(9, 6);
    expect(press(KEY.home).timeStart).toBeCloseTo(minuteMap().indexToTime(0) - MIN / 2, -1);
    const end = press(KEY.end);
    expect((end.timeEnd - minuteMap().indexToTime(1999)) / MIN).toBeCloseTo(12.5, 6);
    expect(press(KEY.zoomIn).barSpacing).toBeCloseTo(end.barSpacing * 1.1, 9);
    expect(press(KEY.zoomOut, MOD.shift).barSpacing).toBeCloseTo((end.barSpacing * 1.1) / 1.25, 9);
    const n = viewports().length;
    input("key", [INPUT.key, KEY.zoomIn, 0, 0, MOD.ctrl, 0]); // browser zoom: ignored
    frame();
    expect(viewports().length).toBe(n);
    expect(press(KEY.home, MOD.ctrl).barSpacing).toBe(6);
  });
});

describe("Scenario: Inertia respects reduced-motion settings (through the runtime)", () => {
  it("init.reducedMotion: a flick stops at the release position with no glide frame", () => {
    make(1064, 624, null, true);
    flick();
    frame();
    const n = viewports().length;
    frame(5);
    expect([viewports().length, pending.length]).toEqual([n, 0]);
  });

  it("setMotion(reduce) mid-coast stops the glide; setMotion(false) restores it", () => {
    make(1064, 624);
    flick();
    frame(2);
    rt.handle({ t: "command", id: 1, cmd: { k: "setMotion", reduce: true } });
    frame();
    const n = viewports().length;
    frame(5);
    expect(viewports().length).toBe(n);
    rt.handle({ t: "command", id: 1, cmd: { k: "setMotion", reduce: false } });
    flick();
    frame(3);
    expect(viewports().length).toBeGreaterThan(n + 2);
  });

  it("a malformed setMotion or init.reducedMotion is rejected at the boundary", () => {
    make(1064, 624);
    out = [];
    rt.handle({ t: "command", id: 1, cmd: { k: "setMotion", reduce: "yes" } });
    const canvas = { width: 1, height: 1, getContext: () => null };
    rt.handle({ t: "init", id: 2, canvas, dpr: 1, theme: {}, config: {}, reducedMotion: 1 });
    expect(
      out.filter((m) => m.t === "error").map((m) => (m as { message: string }).message),
    ).toEqual(["malformed command", "malformed init"]);
  });
});
