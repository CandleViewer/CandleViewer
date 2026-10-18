// E17-T04 S2 (23 7.5): at most 5 resyncs per topic per minute. The gateway revokes the subscription
// on the sixth, so the guard defers it instead. The budget is the `ch`'s, the wait is the stream's: a
// live and a replay stream of one `ch` each keep a request, served oldest first. Fake timers drive
// both the clock and the wake-up.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createResyncGuard,
  RESYNC_LIMIT,
  RESYNC_MARGIN_MS,
  RESYNC_WINDOW_MS,
  type ResyncGuard,
} from "../../../src/lib/ws/core/resyncGuard";
import { topicKey } from "../../../src/lib/ws/core/sequencer";

const REOPEN = RESYNC_WINDOW_MS + RESYNC_MARGIN_MS; // a stamp stops counting once this old
const BOOK = "book.BTCUSDT.50";
const TRADES = "trades.BTCUSDT";
const LIVE = topicKey(BOOK); // the two streams of one `ch` that wait on their own
const REPLAY = topicKey(BOOK, "bb000000-0000-4000-8000-000000000001");

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

/** Moves the fake clock to an absolute time (it starts at 0). */
const advanceTo = (ms: number) => vi.advanceTimersByTime(ms - performance.now());
/** Spends the whole budget of `ch` at the current instant. */
const fill = (guard: ResyncGuard, ch = BOOK) => {
  for (let i = 0; i < RESYNC_LIMIT; i += 1) {
    expect(guard.request(ch, topicKey(ch), vi.fn())).toBe("sent");
  }
};

/** A guard whose timers are fired by hand, against a clock the test owns. */
function manual() {
  let at = 0;
  const timers: (() => void)[] = [];
  const delays: number[] = [];
  const guard = createResyncGuard({
    now: () => at,
    setTimer: (fn, ms) => {
      delays.push(ms);
      timers.push(fn);
    },
    clearTimer: () => undefined,
  });
  return {
    guard,
    /** The delay of every timer the guard set, in order. */
    delays,
    /** Moves the clock without waking anything: a timer that is late. */
    time: (to: number) => {
      at = to;
    },
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
    expect(guard.request(BOOK, LIVE, sixth)).toBe("deferred");
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
      expect(guard.request(BOOK, LIVE, vi.fn())).toBe("sent");
    }
    advanceTo(50_000);
    const sixth = vi.fn();
    expect(guard.request(BOOK, LIVE, sixth)).toBe("deferred"); // the stamp at 0 leaves at 61 s
    advanceTo(REOPEN - 1);
    expect(sixth).not.toHaveBeenCalled();
    advanceTo(REOPEN);
    expect(sixth).toHaveBeenCalledOnce();
    advanceTo(62_000);
    const seventh = vi.fn();
    expect(guard.request(BOOK, LIVE, seventh)).toBe("deferred"); // counted: 10, 20, 30, 40, 61 s
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
    guard.request(BOOK, LIVE, first);
    expect(guard.request(BOOK, LIVE, latest)).toBe("deferred");
    advanceTo(REOPEN);
    expect([first.mock.calls.length, latest.mock.calls.length]).toEqual([0, 1]);
  });

  it("keeps a budget per topic", () => {
    const guard = createResyncGuard();
    fill(guard);
    expect(guard.request(TRADES, topicKey(TRADES), vi.fn())).toBe("sent");
  });

  it("cancel drops the waiting request but not the budget", () => {
    const guard = createResyncGuard();
    fill(guard);
    const send = vi.fn();
    guard.request(BOOK, LIVE, send);
    guard.cancel(BOOK, LIVE);
    guard.cancel(BOOK, LIVE); // nothing waits any more: a no-op
    expect(guard.waiting).toBe(0);
    expect(vi.getTimerCount()).toBe(0); // stopped, not left to fire on nothing
    expect(guard.request(BOOK, LIVE, vi.fn())).toBe("deferred"); // the five stamps still count
    advanceTo(REOPEN);
    expect(send).not.toHaveBeenCalled();
  });

  it("forget and reset drop the budget too, and reset stops every timer", () => {
    const guard = createResyncGuard();
    fill(guard);
    guard.forget(BOOK);
    fill(guard); // a new subscription has a new window
    const send = vi.fn();
    guard.request(BOOK, LIVE, send);
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
    guard.request(BOOK, LIVE, send);
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
    guard.request(BOOK, LIVE, send);
    guard.cancel(BOOK, LIVE);
    fire(REOPEN);
    expect(send).not.toHaveBeenCalled();
  });
});

// A live and a replay stream of one `ch` share the gateway's budget but not its requests: before this,
// one queue slot per `ch` let the later stream replace the earlier, which then stayed `resyncing` for good.
describe("resync guard: the streams of one ch", () => {
  it("keeps a request per stream and serves them oldest first when the window reopens", () => {
    const guard = createResyncGuard();
    fill(guard);
    const sent: string[] = [];
    expect(guard.request(BOOK, LIVE, () => sent.push("live"))).toBe("deferred");
    expect(guard.request(BOOK, REPLAY, () => sent.push("replay"))).toBe("deferred");
    expect(guard.waiting).toBe(2);
    advanceTo(REOPEN - 1);
    expect(sent).toEqual([]);
    advanceTo(REOPEN);
    expect(sent).toEqual(["live", "replay"]);
    expect([guard.waiting, vi.getTimerCount()]).toEqual([0, 0]);
  });

  it("gives each waiting stream the slot that opens, oldest first, and never an early one", () => {
    const guard = createResyncGuard();
    for (const at of [0, 10_000, 20_000, 30_000, 40_000]) {
      advanceTo(at);
      expect(guard.request(BOOK, LIVE, vi.fn())).toBe("sent");
    }
    advanceTo(50_000);
    const sent: string[] = [];
    guard.request(BOOK, LIVE, () => sent.push("live"));
    guard.request(BOOK, REPLAY, () => sent.push("replay"));
    advanceTo(REOPEN); // the stamp of 0 s leaves: one slot
    expect(sent).toEqual(["live"]);
    expect(guard.waiting).toBe(1);
    advanceTo(10_000 + REOPEN - 1); // and the next at 10 s + the window
    expect(sent).toEqual(["live"]);
    advanceTo(10_000 + REOPEN);
    expect(sent).toEqual(["live", "replay"]);
  });

  it("queues a newcomer behind the streams already waiting, even when the budget has opened by then", () => {
    const { guard, fire, time } = manual();
    fill(guard);
    const sent: string[] = [];
    guard.request(BOOK, LIVE, () => sent.push("live"));
    time(REOPEN + 5); // the timer is late: the budget is open and `live` has not been served yet
    expect(guard.request(BOOK, REPLAY, () => sent.push("replay"))).toBe("deferred");
    fire(REOPEN + 5);
    expect(sent).toEqual(["live", "replay"]);
  });

  it("replaces a stream's own waiting send in the place it held, and leaves the others'", () => {
    const guard = createResyncGuard();
    fill(guard);
    const sent: string[] = [];
    guard.request(BOOK, LIVE, () => sent.push("live 1"));
    guard.request(BOOK, REPLAY, () => sent.push("replay"));
    guard.request(BOOK, LIVE, () => sent.push("live 2"));
    expect(guard.waiting).toBe(2);
    advanceTo(REOPEN);
    expect(sent).toEqual(["live 2", "replay"]);
  });

  it("cancels one stream's request and leaves its twin's, and the timer with the last one", () => {
    const guard = createResyncGuard();
    fill(guard);
    const live = vi.fn();
    const replay = vi.fn();
    guard.request(BOOK, LIVE, live);
    guard.request(BOOK, REPLAY, replay);
    guard.cancel(BOOK, LIVE);
    guard.cancel(BOOK, "book.BTCUSDT.50#nobody"); // nothing waits for it: a no-op
    guard.cancel(TRADES, REPLAY); // and nothing waits for the `ch` at all
    expect([guard.waiting, vi.getTimerCount()]).toEqual([1, 1]);
    guard.cancel(BOOK, REPLAY); // the last one: nothing is left to wake
    expect([guard.waiting, vi.getTimerCount()]).toEqual([0, 0]);
    advanceTo(REOPEN);
    expect([live.mock.calls.length, replay.mock.calls.length]).toEqual([0, 0]);
  });

  it("serves the twin that stays when the other is cancelled", () => {
    const guard = createResyncGuard();
    fill(guard);
    const live = vi.fn();
    const replay = vi.fn();
    guard.request(BOOK, LIVE, live);
    guard.request(BOOK, REPLAY, replay);
    guard.cancel(BOOK, LIVE);
    advanceTo(REOPEN);
    expect([live.mock.calls.length, replay.mock.calls.length]).toEqual([0, 1]);
  });

  it("sleeps until the next slot opens, and does not poll for it", () => {
    const { guard, fire, time, delays } = manual();
    for (const at of [0, 10_000, 20_000, 30_000, 40_000]) {
      time(at);
      guard.request(BOOK, LIVE, vi.fn());
    }
    time(50_000);
    const sent: string[] = [];
    guard.request(BOOK, LIVE, () => sent.push("live"));
    guard.request(BOOK, REPLAY, () => sent.push("replay"));
    fire(REOPEN); // the stamp of 0 s has left: one slot, for the oldest
    fire(10_000 + REOPEN);
    expect(sent).toEqual(["live", "replay"]);
    expect(delays).toEqual([REOPEN - 50_000, 10_000]);
  });

  it("forget drops every request waiting for the ch, and reset every request of every ch", () => {
    const guard = createResyncGuard();
    fill(guard);
    fill(guard, TRADES);
    const sent = vi.fn();
    guard.request(BOOK, LIVE, sent);
    guard.request(BOOK, REPLAY, sent);
    guard.request(TRADES, topicKey(TRADES), sent);
    guard.forget(BOOK);
    expect([guard.waiting, vi.getTimerCount()]).toEqual([1, 1]); // trades still waits
    guard.reset();
    expect([guard.waiting, vi.getTimerCount()]).toEqual([0, 0]);
    advanceTo(REOPEN);
    expect(sent).not.toHaveBeenCalled();
  });

  it("does not retry a send that threw, and the streams behind it still go", () => {
    const { guard, fire } = manual();
    fill(guard);
    const behind = vi.fn();
    const boom = vi.fn(() => {
      throw new Error("send failed");
    });
    guard.request(BOOK, LIVE, boom);
    guard.request(BOOK, REPLAY, behind);
    expect(() => fire(REOPEN)).toThrow("send failed");
    expect(guard.waiting).toBe(1); // the one that threw is gone: it is not retried in a loop
    fire(REOPEN); // the timer set while unwinding
    expect([boom.mock.calls.length, behind.mock.calls.length, guard.waiting]).toEqual([1, 1, 0]);
  });
});
