// E24-S05 (#780): the hook's lifecycle carried from #5764's review (6625588237 U3) — StrictMode's double effect
// leaves one live subscription, a window change never shows the old window's feed, and a lost client shows none.
import { act, renderHook } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setActiveClient } from "../../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../../src/lib/ws/client/createWsClient";
import type { LiqClock } from "../../../../src/features/derivatives/liquidations/liquidationFeed";
import { useLiquidationFeed } from "../../../../src/features/derivatives/liquidations/useLiquidationFeed";
import { fakeClient } from "../../tape/fakeFeed";

const clock: LiqClock = { raf: () => 1, caf: () => undefined, now: () => 0 };
const loadHistory = () => new Promise<never>(() => undefined);
const base = { paneId: "l", clock, loadHistory, fromMs: 0, toMs: 60_000 };

const install = () => {
  const fake = fakeClient();
  act(() => setActiveClient(fake.client as unknown as WsClientHandle));
  return fake;
};

afterEach(() => act(() => setActiveClient(null)));

describe("useLiquidationFeed lifecycle (#5764 U3)", () => {
  it("leaves one live subscription under StrictMode's double effect", () => {
    const fake = install();
    const wrapper = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>;
    const { result } = renderHook(() => useLiquidationFeed("BTCUSDT", base), { wrapper });
    const live = fake.handles.filter((h) => vi.mocked(h.release).mock.calls.length === 0);
    expect(live).toHaveLength(1);
    expect(result.current?.symbol).toBe("BTCUSDT");
  });

  it("never shows the old window's feed, and restarts for the new one", () => {
    const fake = install();
    const { result, rerender } = renderHook(
      ({ toMs }: { toMs: number }) => useLiquidationFeed("BTCUSDT", { ...base, toMs }),
      { initialProps: { toMs: 60_000 } },
    );
    const first = result.current;
    rerender({ toMs: 120_000 });
    expect(result.current).not.toBe(first);
    expect(result.current?.window.toMs).toBe(120_000);
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
  });

  it("shows no feed once the client is lost, and releases it", () => {
    const fake = install();
    const { result } = renderHook(() => useLiquidationFeed("BTCUSDT", base));
    expect(result.current).not.toBeNull();
    act(() => setActiveClient(null));
    expect(result.current).toBeNull();
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
  });
});
