// E24-S03 (#778) BQ 2: one shared 1 Hz tick: one timer for every subscriber, aligned past each whole second
// of its own clock, cleared with the last subscriber.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSecondTick } from "../src/components/index.js";

describe("createSecondTick", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.UTC(2026, 9, 27, 7, 59, 0, 400));
  });
  afterEach(() => vi.useRealTimers());

  it("holds one timer for many subscribers and clears it with the last", () => {
    const tick = createSecondTick();
    const a = vi.fn();
    const b = vi.fn();
    const offA = tick.subscribe(a);
    const offB = tick.subscribe(b);
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(3_000);
    expect(a).toHaveBeenCalledTimes(3);
    expect(b).toHaveBeenCalledTimes(3);
    offA();
    expect(vi.getTimerCount()).toBe(1);
    offB();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("fires just past each whole second of its own clock, a skewed one included", () => {
    const skew = -3_000.25; // the local clock 3 s ahead of the exchange (and a fraction)
    const tick = createSecondTick({ now: () => Date.now() + skew });
    const seen: number[] = [];
    const off = tick.subscribe(() => seen.push(tick.now() % 1000));
    vi.advanceTimersByTime(4_000);
    off();
    expect(seen).toHaveLength(4);
    for (const ms of seen) expect(ms).toBeGreaterThanOrEqual(0.5); // 1 ms past, within float error
    for (const ms of seen) expect(ms).toBeLessThan(2);
  });

  it("re-arms for a subscriber added later and stops calling one that left", () => {
    const tick = createSecondTick();
    const a = vi.fn();
    const off = tick.subscribe(a);
    off();
    vi.advanceTimersByTime(2_000);
    expect(a).not.toHaveBeenCalled();
    const b = vi.fn();
    const offB = tick.subscribe(() => {
      b();
      offB();
    });
    vi.advanceTimersByTime(2_000);
    expect(b).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("takes injected timers", () => {
    const runs: (() => void)[] = [];
    const clear = vi.fn();
    const tick = createSecondTick({
      now: () => 10_250,
      setTimeout: (run, ms) => {
        expect(ms).toBe(751);
        return runs.push(run);
      },
      clearTimeout: clear,
    });
    const off = tick.subscribe(() => undefined);
    runs[0]?.();
    expect(runs).toHaveLength(2);
    off();
    expect(clear).toHaveBeenCalledWith(2);
  });

  it("contains a throwing listener: the others still run in that tick and the next tick still fires", () => {
    const rethrown: Array<() => void> = [];
    const spy = vi.spyOn(globalThis, "queueMicrotask").mockImplementation((run) => {
      rethrown.push(run);
    });
    try {
      const tick = createSecondTick();
      const boom = new Error("listener fault");
      const before = vi.fn();
      const after = vi.fn();
      const off = [
        tick.subscribe(before),
        tick.subscribe(() => {
          throw boom;
        }),
        tick.subscribe(after),
      ];
      vi.advanceTimersByTime(1_000);
      expect(before).toHaveBeenCalledTimes(1);
      expect(after).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(1);
      vi.advanceTimersByTime(1_000);
      expect(before).toHaveBeenCalledTimes(2);
      expect(after).toHaveBeenCalledTimes(2);
      expect(rethrown).toHaveLength(2);
      expect(() => rethrown[0]?.()).toThrow(boom);
      for (const o of off) o();
    } finally {
      spy.mockRestore();
    }
  });
});
