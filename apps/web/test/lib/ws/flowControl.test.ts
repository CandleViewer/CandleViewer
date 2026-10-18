// E17-T04 S4 (23 8.5; C8): flow control on its own, where the engine's fake gateway cannot reach:
// what leaving a topic forgets.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createFlowControl } from "../../../src/lib/ws/core/flowControl";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("flow control", () => {
  it("lets go of a topic that was collapsed, and forgets it with its last consumer", () => {
    const consumers = [
      { spec: { ch: "trades.BTCUSDT", paneId: "p1", priority: "focused" as const }, rs: undefined },
    ];
    const flow = createFlowControl({
      consumers: () => consumers,
      ctl: vi.fn(),
      changed: vi.fn(),
      minThrottleMs: () => 50,
    });
    flow.setPane("p1", { visibility: "collapsed", tabHidden: false });
    expect(flow.isReleased("trades.BTCUSDT")).toBe(true);
    consumers.length = 0; // the last consumer is gone
    flow.forget("trades.BTCUSDT");
    expect(flow.isReleased("trades.BTCUSDT")).toBe(false);
  });
});
