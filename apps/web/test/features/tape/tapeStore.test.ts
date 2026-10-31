// E22-S01 (#714) PR-A: the coarse store, published at most twice a second (C-69, D4-07, BQ-209).
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  createTapeStore,
  INITIAL_TAPE_SNAPSHOT,
  PUBLISH_INTERVAL_MS,
  useTapeSnapshot,
  type FrameReport,
} from "../../../src/features/tape/model/tapeStore";

const report = (appended: number, over: Partial<FrameReport> = {}): FrameReport => ({
  appended,
  rows: 0,
  seams: 0,
  notKept: 0,
  lastPrintTsMs: undefined,
  threshold: undefined,
  ...over,
});

describe("tape store", () => {
  it("publishes the rate and prints per frame every 500 ms, never per frame (S01-u-03)", () => {
    const store = createTapeStore();
    const listener = vi.fn();
    store.subscribe(listener);
    // 2 000 prints/s at 50 Hz: 40 per frame, for 3 s
    for (let f = 0; f < 150; f += 1) store.frame(f * 20, report(40, { rows: f }));
    expect(PUBLISH_INTERVAL_MS).toBe(500);
    expect(listener).toHaveBeenCalledTimes(6); // 3 s at 2 Hz, never per frame
    expect(store.getSnapshot()).toMatchObject({ ratePerSec: 2000, perFrame: 40, rows: 125 });
  });

  it("windows the rate to the last second", () => {
    const store = createTapeStore();
    store.frame(0, report(100));
    store.frame(600, report(50));
    store.frame(1200, report(10)); // the frame at 0 has left the window
    expect(store.getSnapshot()).toMatchObject({ ratePerSec: 60, perFrame: 30 });
  });

  it("drops the oldest sample when more frames than its slots arrive inside a second", () => {
    const store = createTapeStore();
    for (let f = 0; f <= 1000; f += 1) store.frame(f, report(1));
    expect(store.getSnapshot().ratePerSec).toBe(512);
  });

  it("carries the frame's rows, seams, not-kept count, last print and threshold", () => {
    const store = createTapeStore();
    store.frame(0, report(1, { rows: 5, seams: 1, notKept: 2, lastPrintTsMs: 42, threshold: "9" }));
    expect(store.getSnapshot()).toMatchObject({
      rows: 5,
      seams: 1,
      notKept: 2,
      lastPrintTsMs: 42,
      threshold: "9",
    });
  });

  it("does not publish an unchanged snapshot", () => {
    const store = createTapeStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.frame(0, report(0));
    store.frame(600, report(0));
    expect(listener).not.toHaveBeenCalled();
    expect(store.getSnapshot()).toBe(INITIAL_TAPE_SNAPSHOT);
  });

  it("publishes a feed transition at once, and only a change", () => {
    const store = createTapeStore();
    const listener = vi.fn();
    const off = store.subscribe(listener);
    store.setFeed("pending");
    store.setFeed("pending");
    store.setFeed("live");
    expect(listener).toHaveBeenCalledTimes(2);
    off();
    store.setFeed("stale");
    expect(listener).toHaveBeenCalledTimes(2);
    expect(store.getSnapshot().feed).toBe("stale");
  });

  it("re-renders a reader on a publish, and reads the initial state with no store", () => {
    const store = createTapeStore();
    const { result } = renderHook(() => useTapeSnapshot(store));
    expect(result.current.feed).toBe("idle");
    act(() => store.setFeed("live"));
    expect(result.current.feed).toBe("live");
    const none = renderHook(() => useTapeSnapshot(null));
    expect(none.result.current).toBe(INITIAL_TAPE_SNAPSHOT);
  });
});
