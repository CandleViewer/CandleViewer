// E17-T04 S3 (23 8.5, C9): rendering follows the display, never the feed.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createFrameScheduler,
  FRAME_BUDGET_MS,
  type FrameMark,
} from "../../../src/lib/ws/client/frameScheduler";

type Batch = ReadonlyMap<string, number>;

/** A manual requestAnimationFrame: `frame(t)` runs what was asked for, as the display would. */
function fakeDisplay() {
  const requested = new Map<number, (frameTimeMs: number) => void>();
  let handle = 0;
  return {
    raf: (callback: (frameTimeMs: number) => void): number => {
      handle += 1;
      requested.set(handle, callback);
      return handle;
    },
    caf: (id: number): void => {
      requested.delete(id);
    },
    pending: () => requested.size,
    frame: (frameTimeMs: number): void => {
      const callbacks = [...requested.values()];
      requested.clear();
      for (const callback of callbacks) callback(frameTimeMs);
    },
  };
}

afterEach(() => vi.useRealTimers());

describe("frame scheduler (C9)", () => {
  it("Render is decoupled from arrival", () => {
    const display = fakeDisplay();
    const render = vi.fn<(batch: Batch) => void>();
    const scheduler = createFrameScheduler<number>({ render, raf: display.raf, caf: display.caf });
    for (let seq = 1; seq <= 500; seq += 1) scheduler.post("book.BTCUSDT.50", seq); // 500 frames, one animation frame
    expect(render).not.toHaveBeenCalled(); // nothing is applied from the arrival path
    expect(display.pending()).toBe(1); // one frame requested, not 500
    display.frame(16); // the next animation frame applies it
    expect(render).toHaveBeenCalledTimes(1);
    expect(render.mock.calls[0]?.[0]).toEqual(new Map([["book.BTCUSDT.50", 500]]));
    expect([scheduler.renders, scheduler.overruns]).toEqual([1, 0]);
    expect(display.pending()).toBe(0); // idle frames cost nothing
  });

  it("hands every key that changed to one render, the latest value of each", () => {
    const display = fakeDisplay();
    const render = vi.fn<(batch: Batch) => void>();
    const scheduler = createFrameScheduler<number>({ render, raf: display.raf, caf: display.caf });
    scheduler.post("a", 1);
    scheduler.post("b", 2);
    scheduler.post("a", 3);
    display.frame(16);
    expect(render.mock.calls).toEqual([
      [
        new Map([
          ["a", 3],
          ["b", 2],
        ]),
      ],
    ]);
  });

  it("counts a render over the frame budget as an overrun, and marks the apply and the paint", () => {
    const display = fakeDisplay();
    const marks: [FrameMark, number][] = [];
    let clock = 0;
    let renderMs = FRAME_BUDGET_MS + 1;
    const scheduler = createFrameScheduler<number>({
      render: () => {
        clock += renderMs;
      },
      raf: display.raf,
      caf: display.caf,
      now: () => clock,
      mark: (name, at) => marks.push([name, at]),
    });
    scheduler.post("a", 1);
    display.frame(0);
    expect(scheduler.overruns).toBe(1);
    expect(marks).toEqual([
      ["state.apply", 0],
      ["paint", FRAME_BUDGET_MS + 1],
    ]);
    renderMs = FRAME_BUDGET_MS; // exactly the budget is not over it
    scheduler.post("a", 2);
    display.frame(20);
    expect([scheduler.renders, scheduler.overruns]).toEqual([2, 1]);
  });

  it("applies a post made while rendering on the next frame, and survives a render that throws", () => {
    const display = fakeDisplay();
    const seen: string[][] = [];
    let explode = true;
    const scheduler = createFrameScheduler<number>({
      render: (batch) => {
        seen.push([...batch.keys()]);
        if (batch.has("a")) scheduler.post("b", 2);
        if (batch.has("boom") && explode) throw new Error("boom");
      },
      raf: display.raf,
      caf: display.caf,
    });
    scheduler.post("a", 1);
    display.frame(16);
    expect(display.pending()).toBe(1);
    display.frame(32);
    expect(seen).toEqual([["a"], ["b"]]);
    scheduler.post("boom", 1);
    expect(() => display.frame(48)).toThrow("boom");
    explode = false;
    scheduler.post("boom", 2); // the scheduler asks for the next frame again
    display.frame(64);
    expect(scheduler.renders).toBe(4);
  });

  it("stop() cancels the pending frame, drops the slots and ignores later posts", () => {
    const display = fakeDisplay();
    const render = vi.fn<(batch: Batch) => void>();
    const scheduler = createFrameScheduler<number>({ render, raf: display.raf, caf: display.caf });
    scheduler.post("a", 1);
    scheduler.stop();
    expect(display.pending()).toBe(0);
    scheduler.post("a", 2);
    display.frame(16);
    expect(render).not.toHaveBeenCalled();
  });

  it("drops the slots at stop, and holds none of the posts after it, even when the display cannot cancel the frame", () => {
    const display = fakeDisplay();
    const render = vi.fn<(batch: Batch) => void>();
    const scheduler = createFrameScheduler<number>({
      render,
      raf: display.raf,
      caf: () => undefined,
    });
    scheduler.post("a", 1);
    scheduler.stop();
    for (let n = 0; n < 10_000; n += 1) scheduler.post(`k${n}`, n); // ignored: nothing is held
    display.frame(16); // the frame that was not cancelled
    expect(render).toHaveBeenCalledTimes(1);
    expect(render.mock.calls[0]?.[0].size).toBe(0);
  });

  it("defaults to requestAnimationFrame, cancelAnimationFrame and performance.now", () => {
    vi.useFakeTimers();
    const render = vi.fn<(batch: Batch) => void>();
    const scheduler = createFrameScheduler<number>({ render });
    scheduler.post("a", 1);
    vi.advanceTimersByTime(16);
    expect(render).toHaveBeenCalledTimes(1);
    scheduler.post("a", 2);
    scheduler.stop();
    vi.advanceTimersByTime(100);
    expect(render).toHaveBeenCalledTimes(1);
  });
});
