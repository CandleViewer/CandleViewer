// E17-T04 S2 (23 7.5): at most 5 resyncs per topic per minute. The gateway revokes the subscription
// on the sixth, so the guard defers it instead. Fake timers drive both the clock and the wake-up.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createResyncGuard,
  RESYNC_LIMIT,
  RESYNC_MARGIN_MS,
  RESYNC_WINDOW_MS,
  type ResyncGuard,
} from "../../../src/lib/ws/core/resyncGuard";

const REOPEN = RESYNC_WINDOW_MS + RESYNC_MARGIN_MS; // a stamp stops counting once this old
const BOOK = "book.BTCUSDT.50";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

/** Moves the fake clock to an absolute time (it starts at 0). */
const advanceTo = (ms: number) => vi.advanceTimersByTime(ms - performance.now());
/** Spends the whole budget of `BOOK` at the current instant. */
const fill = (guard: ResyncGuard) => {
  for (let i = 0; i < RESYNC_LIMIT; i += 1) expect(guard.request(BOOK, vi.fn())).toBe("sent");
};

/** A guard whose timers are fired by hand, against a clock the test owns. */
function manual() {
  let at = 0;
  const timers: (() => void)[] = [];
  const guard = createResyncGuard({
    now: () => at,
    setTimer: (fn) => timers.push(fn),
    clearTimer: () => undefined,
  });
  return {
    guard,
    fire: (to: number) => {
      at = to;
      timers.shift()?.();
    },
  };
}

describe("resync guard", () => {
  it("sends five at once and defers the sixth until the window reopens, never early", () => {
    const guard = createResyncGuard();
    fill(guard);
    const sixth = vi.fn();
    expect(guard.request(BOOK, sixth)).toBe("deferred");
    expect(guard.waiting).toBe(1);
    advanceTo(RESYNC_WINDOW_MS); // the gateway's own minute is not enough: its clock and the transit differ
    expect(sixth).not.toHaveBeenCalled();
    advanceTo(REOPEN - 1);
    expect(sixth).not.toHaveBeenCalled();
    advanceTo(REOPEN);
    expect(sixth).toHaveBeenCalledOnce();
    expect(guard.waiting).toBe(0);
  });

  it("slides: the window reopens one stamp at a time, from the oldest still counted", () => {
    const guard = createResyncGuard();
    for (const at of [0, 10_000, 20_000, 30_000, 40_000]) {
      advanceTo(at);
      expect(guard.request(BOOK, vi.fn())).toBe("sent");
    }
    advanceTo(50_000);
    const sixth = vi.fn();
    expect(guard.request(BOOK, sixth)).toBe("deferred"); // the stamp at 0 leaves at 61 s
    advanceTo(REOPEN - 1);
    expect(sixth).not.toHaveBeenCalled();
    advanceTo(REOPEN);
    expect(sixth).toHaveBeenCalledOnce();
    advanceTo(62_000);
    const seventh = vi.fn();
    expect(guard.request(BOOK, seventh)).toBe("deferred"); // counted: 10, 20, 30, 40, 61 s
    advanceTo(10_000 + REOPEN - 1);
    expect(seventh).not.toHaveBeenCalled();
    advanceTo(10_000 + REOPEN);
    expect(seventh).toHaveBeenCalledOnce();
  });

  it("coalesces: while one request waits, the latest send replaces it and runs once", () => {
    const guard = createResyncGuard();
    fill(guard);
    const first = vi.fn();
    const latest = vi.fn();
    guard.request(BOOK, first);
    expect(guard.request(BOOK, latest)).toBe("deferred");
    advanceTo(REOPEN);
    expect([first.mock.calls.length, latest.mock.calls.length]).toEqual([0, 1]);
  });

  it("keeps a budget per topic", () => {
    const guard = createResyncGuard();
    fill(guard);
    expect(guard.request("trades.BTCUSDT", vi.fn())).toBe("sent");
  });

  it("cancel drops the waiting request but not the budget", () => {
    const guard = createResyncGuard();
    fill(guard);
    const send = vi.fn();
    guard.request(BOOK, send);
    guard.cancel(BOOK);
    guard.cancel(BOOK); // nothing waits any more: a no-op
    expect(guard.waiting).toBe(0);
    expect(vi.getTimerCount()).toBe(0); // stopped, not left to fire on nothing
    expect(guard.request(BOOK, vi.fn())).toBe("deferred"); // the five stamps still count
    advanceTo(REOPEN);
    expect(send).not.toHaveBeenCalled();
  });

  it("forget and reset drop the budget too, and reset stops every timer", () => {
    const guard = createResyncGuard();
    fill(guard);
    guard.forget(BOOK);
    fill(guard); // a new subscription has a new window
    const send = vi.fn();
    guard.request(BOOK, send);
    guard.reset();
    expect(guard.waiting).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
    fill(guard); // a new connection starts from nothing: five more go at once, at the same instant
    advanceTo(REOPEN);
    expect(send).not.toHaveBeenCalled();
  });

  it("re-arms a timer that fires early instead of sending early", () => {
    const { guard, fire } = manual();
    fill(guard);
    const send = vi.fn();
    guard.request(BOOK, send);
    fire(REOPEN - 10);
    expect(send).not.toHaveBeenCalled();
    expect(guard.waiting).toBe(1);
    fire(REOPEN);
    expect(send).toHaveBeenCalledOnce();
  });

  it("ignores a timer that fires after its request was cancelled", () => {
    const { guard, fire } = manual();
    fill(guard);
    const send = vi.fn();
    guard.request(BOOK, send);
    guard.cancel(BOOK);
    fire(REOPEN);
    expect(send).not.toHaveBeenCalled();
  });
});
