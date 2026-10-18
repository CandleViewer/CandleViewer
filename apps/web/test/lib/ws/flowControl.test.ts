// E17-T04 S4 (23 6.1.1): flow control on its own, where the engine's fake gateway cannot reach: a server
// that names no heatmap bucket runs the default (rule 3).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createFlowControl } from "../../../src/lib/ws/core/flowControl";
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
});
