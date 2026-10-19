// E17-T04 S4 (23 6.1.1): flow control on its own, where the engine's fake gateway cannot reach: a server
// that names no heatmap bucket runs the default (rule 3).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConsumerSpec } from "../../../src/lib/ws/api";
import { createFlowControl, REFUSED_BACKOFF_MS } from "../../../src/lib/ws/core/flowControl";
import { platformTimers } from "../../../src/lib/ws/policy/timers";

const HEATMAP = "heatmap.BTCUSDT";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const visible = (cssWidth: number) =>
  ({ visibility: "visible", tabHidden: false, size: { cssWidth, dpr: 1 } }) as const;

describe("flow control", () => {
  it("lets go of a topic that was collapsed, and forgets it with its last consumer", () => {
    const consumers = [
      { spec: { ch: "trades.BTCUSDT", paneId: "p1", priority: "focused" as const }, rs: undefined },
    ];
    const flow = createFlowControl(
      { consumers: () => consumers, ctl: vi.fn(), changed: vi.fn(), minThrottleMs: () => 50 },
      platformTimers,
    );
    flow.setPane("p1", { visibility: "collapsed", tabHidden: false });
    expect(flow.isReleased("trades.BTCUSDT", undefined)).toBe(true);
    expect(flow.retained).toBe(1); // and the flag is all that is kept of it
    consumers.length = 0; // the last consumer is gone
    flow.forget("trades.BTCUSDT", undefined);
    expect(flow.isReleased("trades.BTCUSDT", undefined)).toBe(false);
  });

  it("takes a heatmap whose confirmed options name no bucket for the server's 500 ms (rule 3)", () => {
    const ctl = vi.fn();
    const flow = createFlowControl(
      {
        consumers: () => [
          { spec: { ch: HEATMAP, paneId: "p1", priority: "focused" }, rs: undefined },
        ],
        ctl,
        changed: vi.fn(),
        minThrottleMs: () => 50,
      },
      platformTimers,
    );
    flow.setPane("p1", visible(5_400)); // 900 s over 5 400 px derives 500 ms
    flow.confirmed(HEATMAP, undefined, {}); // the server named no bucket
    vi.advanceTimersByTime(1_000);
    expect(ctl).not.toHaveBeenCalled();
    flow.setPane("p1", visible(1_190)); // 1 000 ms now: a change from the 500 the server runs
    vi.advanceTimersByTime(1_000);
    expect(ctl).toHaveBeenCalledOnce();
    expect(ctl).toHaveBeenCalledWith(HEATMAP, undefined, { time_bucket_ms: 1_000 });
  });

  it("undoes a refused bucket ctl of a server that names no bucket: back at its 500 ms nothing is sent (rule 3, SR-193)", () => {
    const ctl = vi.fn();
    const flow = createFlowControl(
      {
        consumers: () => [
          { spec: { ch: HEATMAP, paneId: "p1", priority: "focused" }, rs: undefined },
        ],
        ctl,
        changed: vi.fn(),
        minThrottleMs: () => 50,
      },
      platformTimers,
    );
    flow.setPane("p1", visible(5_400));
    flow.confirmed(HEATMAP, undefined, {}); // the server named no bucket: it runs 500 ms
    flow.setPane("p1", visible(1_190)); // 1 000 ms is wanted
    vi.advanceTimersByTime(400);
    expect(ctl).toHaveBeenCalledOnce();
    flow.refused(HEATMAP, undefined); // the rebuild budget said no: the server still runs 500 ms
    flow.setPane("p1", visible(5_400)); // and that is what the pane wants again
    vi.advanceTimersByTime(REFUSED_BACKOFF_MS + 1_000);
    expect(ctl).toHaveBeenCalledOnce();
  });

  it("ignores a refusal of a stream that is no longer held: no wait is started for it", () => {
    const flow = createFlowControl(
      { consumers: () => [], ctl: vi.fn(), changed: vi.fn(), minThrottleMs: () => 50 },
      platformTimers,
    );
    const timers = vi.getTimerCount();
    flow.refused(HEATMAP, undefined); // never confirmed, or let go since
    expect(vi.getTimerCount()).toBe(timers);
  });
});

describe("a ch with a live and a replay stream: flow control is per stream (#3439)", () => {
  const RS = "bb000000-0000-4000-8000-000000000001";
  const TRADES = "trades.BTCUSDT";
  const offscreen = { visibility: "offscreen", tabHidden: false } as const;
  const consumer = (ch: string, rs?: string, paneId = "p1") => ({
    spec: { ch, paneId, priority: "focused" } satisfies ConsumerSpec,
    rs,
  });
  /** A flow control over the consumers it is given, and the `ctl`s it sent. */
  function flowOf(consumers: ReturnType<typeof consumer>[]) {
    const ctl = vi.fn();
    const host = { consumers: () => consumers, ctl, changed: vi.fn(), minThrottleMs: () => 50 };
    return { flow: createFlowControl(host, platformTimers), ctl };
  }
  /** Both streams of `TRADES`, held and running at 100 ms. */
  function twins() {
    const { flow, ctl } = flowOf([consumer(TRADES), consumer(TRADES, RS)]);
    flow.confirmed(TRADES, undefined, { throttle_ms: 100 });
    flow.confirmed(TRADES, RS, { throttle_ms: 250 });
    return { flow, ctl };
  }

  it("keeps one denied latch per stream: a reply for another stream does not reopen it", () => {
    const { flow, ctl } = twins();
    flow.setPane("p1", offscreen);
    ctl.mockClear();
    flow.denied(TRADES, undefined); // refused: asked again once, from what is wanted now
    expect(ctl).toHaveBeenCalledTimes(1);
    flow.confirmed(TRADES, RS, { throttle_ms: 1_000 }); // the twin's reply
    flow.confirmed("book.BTCUSDT.50", undefined, { throttle_ms: 50 }); // another ch's
    flow.denied(TRADES, undefined); // refused again: the latch holds, nothing is asked
    expect(ctl).toHaveBeenCalledTimes(1);
    flow.confirmed(TRADES, undefined, { throttle_ms: 100 }); // its own reply reopens it
    expect(ctl).toHaveBeenCalledTimes(2);
  });

  it("keeps no latch for a denial of a stream that is not confirmed: it was let go, or lost with its connection, since the ctl left", () => {
    const { flow, ctl } = flowOf([consumer(TRADES)]);
    flow.denied(TRADES, undefined);
    expect([flow.retained, ctl.mock.calls]).toEqual([0, []]);
  });

  it("waits out a refusal for the refused stream alone, and each stream's wait doubles on its own", () => {
    const { flow, ctl } = twins();
    flow.refused(TRADES, undefined); // 5 s
    flow.refused(TRADES, undefined); // and 10 s for the live stream
    flow.refused(TRADES, RS); // the replay stream's first: 5 s
    flow.setPane("p1", offscreen);
    expect(ctl).not.toHaveBeenCalled();
    vi.advanceTimersByTime(REFUSED_BACKOFF_MS);
    expect(ctl.mock.calls).toEqual([[TRADES, RS, { throttle_ms: 1_000 }]]); // its wait is over, the other's is not
    vi.advanceTimersByTime(REFUSED_BACKOFF_MS);
    expect(ctl.mock.calls.at(-1)).toEqual([TRADES, undefined, { throttle_ms: 1_000 }]);
  });

  it("derives a stream's bucket from the window the server confirmed for it, not its twin's", () => {
    const { flow, ctl } = flowOf([consumer(HEATMAP, undefined), consumer(HEATMAP, RS)]);
    flow.setPane("p1", visible(1_190));
    flow.confirmed(HEATMAP, undefined, { time_bucket_ms: 5_000 }); // the default window: 900 s, 1 000 ms
    flow.confirmed(HEATMAP, RS, { time_bucket_ms: 5_000, window_seconds: 100 }); // its own: 500 ms
    vi.advanceTimersByTime(400);
    expect(ctl.mock.calls).toEqual([
      [HEATMAP, undefined, { time_bucket_ms: 1_000 }],
      [HEATMAP, RS, { time_bucket_ms: 500 }],
    ]);
  });
});
