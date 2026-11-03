// E11-T06: the runtime hands its timeline to a chart's scheduler in bench mode only, so 06 §4.3's
// stage marks exist on bench frames and never on production ones.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { BACKGROUND_TOKEN, type ToWorker } from "../../src/worker/protocol.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FULL } from "../gl/fake-gl.js";

let marks: string[];

function runtime(withTimeline: boolean): RenderRuntime {
  return createRenderRuntime({
    runMode: "inline",
    post: () => undefined,
    requestFrame: (cb) => {
      setTimeout(cb, 16);
    },
    now: () => Date.now(),
    setTimer: (cb, ms) => {
      setTimeout(cb, ms);
    },
    probe: () => FULL,
    ...(withTimeline && { timeline: { mark: (n: string) => marks.push(n) } }),
  });
}

function open(rt: RenderRuntime, bench: boolean): void {
  const ctx = new FakeCtx2D();
  rt.handle({
    t: "init",
    id: 1,
    canvas: { width: 200, height: 100, ctx, getContext: () => ctx },
    dpr: 1,
    theme: { [BACKGROUND_TOKEN]: "#000000" },
    config: { bench, syncGroup: null },
  } satisfies ToWorker);
}

beforeEach(() => {
  vi.useFakeTimers();
  marks = [];
});

afterEach(() => {
  vi.useRealTimers();
});

describe("bench-mode stage marks in the runtime", () => {
  it("marks every stage boundary of a bench-mode frame", () => {
    open(runtime(true), true);
    vi.advanceTimersByTime(16);
    expect(marks[0]).toBe("cv.frame.start");
    expect(marks.at(-1)).toBe("cv.stage.compositePresent");
    expect(marks).toHaveLength(11);
  });

  it("marks nothing for a production chart, even with a timeline available", () => {
    open(runtime(true), false);
    vi.advanceTimersByTime(16);
    expect(marks).toEqual([]);
  });

  it("marks nothing in bench mode on a runtime without a timeline", () => {
    open(runtime(false), true);
    vi.advanceTimersByTime(16);
    expect(marks).toEqual([]);
  });
});
