// E24-S05 (#780): the hook on the active client — one feed and one read, restarted on a symbol, filter or window
// change, released on unmount (every subscription has a teardown test, rules/30).
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setActiveClient } from "../../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../../src/lib/ws/client/createWsClient";
import type { LiqClock } from "../../../../src/features/derivatives/liquidations/liquidationFeed";
import { useLiquidationFeed } from "../../../../src/features/derivatives/liquidations/useLiquidationFeed";
import { fakeClient } from "../../tape/fakeFeed";

const pending = new Map<number, () => void>();
let next = 0;
const clock: LiqClock = {
  raf: (cb) => (pending.set(++next, () => cb(0)), next),
  caf: (h) => void pending.delete(h),
  now: () => 0,
};

const loadHistory = vi.fn(() => new Promise<never>(() => undefined));
const base = { paneId: "l", clock, loadHistory, fromMs: 0, toMs: 60_000 };

const install = () => {
  const fake = fakeClient();
  act(() => setActiveClient(fake.client as unknown as WsClientHandle));
  return fake;
};

afterEach(() => {
  act(() => setActiveClient(null));
  pending.clear();
  loadHistory.mockClear();
});

describe("useLiquidationFeed", () => {
  it("waits for a client and subscribes nothing for a symbol it cannot serve", () => {
    const { result } = renderHook(() => useLiquidationFeed("BTCUSDT", base));
    expect(result.current).toBeNull();
    const fake = install();
    const bad = renderHook(() => useLiquidationFeed("BTC-USDT", base));
    expect(bad.result.current).toBeNull();
    expect(fake.specs.map((s) => s.ch)).toEqual(["liquidations.BTCUSDT"]);
  });

  it("releases the topic and stops the loop on unmount", () => {
    const fake = install();
    const { result, unmount } = renderHook(() => useLiquidationFeed("BTCUSDT", base));
    expect(result.current?.symbol).toBe("BTCUSDT");
    expect(pending.size).toBe(1);
    unmount();
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
    expect(pending.size).toBe(0);
  });

  it("restarts on a filter change and never shows the old filter's feed", () => {
    const fake = install();
    const { result, rerender } = renderHook(
      ({ min }: { min: string | null }) =>
        useLiquidationFeed("BTCUSDT", { ...base, minNotionalUsd: min }),
      { initialProps: { min: null as string | null } },
    );
    rerender({ min: "50000" });
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
    expect(fake.specs[1]?.opts).toEqual({ cluster_window_ms: 0, min_notional_usd: "50000" });
    expect(result.current?.minNotionalUsd).toBe("50000");
  });

  it("restarts on a symbol change", () => {
    const fake = install();
    const { rerender } = renderHook(
      ({ symbol }: { symbol: string }) => useLiquidationFeed(symbol, base),
      { initialProps: { symbol: "BTCUSDT" } },
    );
    rerender({ symbol: "ETHUSDT" });
    expect(fake.specs.map((s) => s.ch)).toEqual(["liquidations.BTCUSDT", "liquidations.ETHUSDT"]);
  });

  it("reads once per mount and once more per symbol change (BQ 3), and not for a bad window", () => {
    install();
    const { rerender } = renderHook(
      ({ symbol }: { symbol: string }) => useLiquidationFeed(symbol, base),
      { initialProps: { symbol: "BTCUSDT" } },
    );
    expect(loadHistory).toHaveBeenCalledTimes(1);
    rerender({ symbol: "BTCUSDT" });
    expect(loadHistory).toHaveBeenCalledTimes(1);
    rerender({ symbol: "ETHUSDT" });
    expect(loadHistory).toHaveBeenCalledTimes(2);
    const bad = renderHook(() => useLiquidationFeed("BTCUSDT", { ...base, toMs: 0 }));
    expect(bad.result.current).toBeNull();
    expect(loadHistory).toHaveBeenCalledTimes(2);
  });

  it("does not restart for an inline loadHistory or clock, and reads through the latest one", () => {
    const fake = install();
    const first = vi.fn(() => new Promise<never>(() => undefined));
    const { rerender } = renderHook(
      ({ load }: { load: typeof first }) =>
        useLiquidationFeed("BTCUSDT", { ...base, loadHistory: load, clock: { ...clock } }),
      { initialProps: { load: first } },
    );
    rerender({ load: vi.fn(() => new Promise<never>(() => undefined)) });
    expect(fake.client.consume).toHaveBeenCalledTimes(1);
    expect(fake.handles[0]?.release).not.toHaveBeenCalled();
    expect(first).toHaveBeenCalledTimes(1);
  });
});
