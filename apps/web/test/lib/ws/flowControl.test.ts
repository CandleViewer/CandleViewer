// E17-T04 S4 (23 6.1.1): flow control on its own, where the engine's fake gateway cannot reach: a server
// that names no heatmap bucket runs the default (rule 3).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
    expect(flow.isReleased("trades.BTCUSDT")).toBe(true);
    consumers.length = 0; // the last consumer is gone
    flow.forget("trades.BTCUSDT");
    expect(flow.isReleased("trades.BTCUSDT")).toBe(false);
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
    flow.confirmed(HEATMAP, {}); // the server named no bucket
    vi.advanceTimersByTime(1_000);
    expect(ctl).not.toHaveBeenCalled();
    flow.setPane("p1", visible(1_190)); // 1 000 ms now: a change from the 500 the server runs
    vi.advanceTimersByTime(1_000);
    expect(ctl).toHaveBeenCalledOnce();
    expect(ctl).toHaveBeenCalledWith(HEATMAP, { time_bucket_ms: 1_000 });
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
    flow.confirmed(HEATMAP, {}); // the server named no bucket: it runs 500 ms
    flow.setPane("p1", visible(1_190)); // 1 000 ms is wanted
    vi.advanceTimersByTime(400);
    expect(ctl).toHaveBeenCalledOnce();
    flow.refused(HEATMAP); // the rebuild budget said no: the server still runs 500 ms
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
    flow.refused(HEATMAP); // never confirmed, or let go since
    expect(vi.getTimerCount()).toBe(timers);
  });
});
