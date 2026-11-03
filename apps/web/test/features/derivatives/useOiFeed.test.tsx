// E24-S01 (#776) slice 1: the hook on the active client — one feed, restarted on a symbol or bar change,
// released on unmount (every subscription has a teardown test, rules/30).
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import type { HistoryResult } from "../../../src/features/derivatives/oi/history";
import type { OiClock } from "../../../src/features/derivatives/oi/oiFeed";
import { useOiFeed } from "../../../src/features/derivatives/oi/useOiFeed";
import { fakeClient } from "../tape/fakeFeed";

const MIN = 60_000;
const pending = new Map<number, () => void>();
let next = 0;
const clock: OiClock = {
  raf: (cb) => (pending.set(++next, () => cb(0)), next),
  caf: (h) => void pending.delete(h),
  now: () => 0,
  wallNow: () => 0,
};
const loadHistory = vi.fn(async (): Promise<HistoryResult> => ({
  kind: "failed",
  status: null,
  code: null,
}));
const analytics = {
  metricToggled: vi.fn(),
  intervalChanged: vi.fn(),
  backfillFailed: vi.fn(),
  backfillAnomaly: vi.fn(),
};
const base = { paneId: "oi", fromMs: 0, toMs: MIN, loadHistory, clock, analytics };

const install = () => {
  const fake = fakeClient();
  act(() => setActiveClient(fake.client as unknown as WsClientHandle));
  return fake;
};

afterEach(() => {
  act(() => setActiveClient(null));
  pending.clear();
  vi.clearAllMocks();
});

describe("useOiFeed", () => {
  it("waits for a client and subscribes nothing for a symbol it cannot serve", () => {
    const { result } = renderHook(() => useOiFeed("BTCUSDT", { ...base, barMs: MIN }));
    expect(result.current).toBeNull();
    const fake = install();
    const bad = renderHook(() => useOiFeed("BTC-USDT", { ...base, barMs: MIN }));
    expect(bad.result.current).toBeNull();
    expect(fake.client.consume).toHaveBeenCalledTimes(1); // the first hook's, now that a client exists
    expect(fake.specs[0]?.ch).toBe("ticker.BTCUSDT");
  });

  it("releases the topic and stops the loop on unmount", () => {
    const fake = install();
    const { result, unmount } = renderHook(() => useOiFeed("BTCUSDT", { ...base, barMs: MIN }));
    expect(result.current?.symbol).toBe("BTCUSDT");
    expect(pending.size).toBe(1);
    unmount();
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
    expect(pending.size).toBe(0);
  });

  it("restarts on a bar change, says interval_changed, and never shows the old bar's feed", () => {
    const fake = install();
    const { result, rerender } = renderHook(
      ({ barMs }: { barMs: number }) => useOiFeed("BTCUSDT", { ...base, barMs }),
      { initialProps: { barMs: MIN } },
    );
    rerender({ barMs: 5 * MIN });
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
    expect(fake.handles).toHaveLength(2);
    expect(result.current?.barMs).toBe(5 * MIN);
    expect(analytics.intervalChanged).toHaveBeenCalledWith("BTCUSDT", MIN, 5 * MIN);
    expect(loadHistory).toHaveBeenCalledTimes(2);
  });

  it("does not rebuild the feed on a re-render with the same window, loader and analytics", () => {
    const fake = install();
    const { result, rerender } = renderHook(() => useOiFeed("BTCUSDT", { ...base, barMs: MIN }));
    const first = result.current;
    rerender();
    rerender();
    expect(result.current).toBe(first);
    expect(fake.handles).toHaveLength(1);
    expect(fake.handles[0]?.release).not.toHaveBeenCalled();
    expect(loadHistory).toHaveBeenCalledTimes(1);
  });

  it("rebuilds the feed when the window changes", () => {
    const fake = install();
    const { rerender } = renderHook(
      ({ toMs }: { toMs: number }) => useOiFeed("BTCUSDT", { ...base, barMs: MIN, toMs }),
      { initialProps: { toMs: MIN } },
    );
    rerender({ toMs: 2 * MIN });
    expect(fake.handles).toHaveLength(2);
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
  });

  it("restarts on a symbol change without an interval event", () => {
    const fake = install();
    const { rerender } = renderHook(
      ({ symbol }: { symbol: string }) => useOiFeed(symbol, { ...base, barMs: MIN }),
      { initialProps: { symbol: "BTCUSDT" } },
    );
    rerender({ symbol: "ETHUSDT" });
    expect(fake.specs.map((s) => s.ch)).toEqual(["ticker.BTCUSDT", "ticker.ETHUSDT"]);
    expect(analytics.intervalChanged).not.toHaveBeenCalled();
  });
});
