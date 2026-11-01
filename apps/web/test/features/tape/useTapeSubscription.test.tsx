// E22-S01 (#714) PR-A: the subscription hook on the active client, behind TAPE_ENABLED (BQ-217).
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { TAPE_ENABLED } from "../../../src/features/tape/flag";
import { useTapeSubscription } from "../../../src/features/tape/useTapeSubscription";
import { fakeClient, fakeDisplay } from "./fakeFeed";
import { snap, items } from "./frames";

const install = () => {
  const fake = fakeClient();
  act(() => setActiveClient(fake.client as unknown as WsClientHandle));
  return fake;
};

afterEach(() => act(() => setActiveClient(null)));

describe("useTapeSubscription", () => {
  it("is off by default: the flag is unset outside the Playwright build", () => {
    expect(TAPE_ENABLED).toBe(false);
    const fake = install();
    const { result } = renderHook(() => useTapeSubscription("BTCUSDT", { paneId: "p" }));
    expect(result.current).toBeNull();
    expect(fake.client.consume).not.toHaveBeenCalled();
  });

  it("subscribes once enabled, marks the pane visible, and releases on unmount", () => {
    const fake = install();
    const display = fakeDisplay();
    const { clock } = display;
    const { result, unmount } = renderHook(() =>
      useTapeSubscription("BTCUSDT", { paneId: "p", enabled: true, clock }),
    );
    expect(result.current?.symbol).toBe("BTCUSDT");
    expect(fake.client.setPane).toHaveBeenCalledWith("p", "visible");
    fake.handles[0]?.queue.push(snap(items(1, 2)));
    display.frame();
    expect(result.current?.ring.length).toBe(2);
    unmount();
    expect(fake.handles[0]?.release).toHaveBeenCalledTimes(1);
    expect(display.pending()).toBe(0);
  });

  it("waits for a client, and moves to a new one", () => {
    const { clock } = fakeDisplay();
    const { result } = renderHook(() =>
      useTapeSubscription("BTCUSDT", { paneId: "p", enabled: true, clock }),
    );
    expect(result.current).toBeNull();
    const first = install();
    expect(result.current).not.toBeNull();
    const second = install();
    expect(first.handles[0]?.release).toHaveBeenCalledTimes(1);
    expect(second.client.consume).toHaveBeenCalledTimes(1);
    act(() => setActiveClient(null));
    expect(second.handles[0]?.release).toHaveBeenCalledTimes(1);
    expect(result.current).toBeNull();
  });

  it("resubscribes on a symbol change and subscribes to nothing for an invalid symbol", () => {
    const fake = install();
    const { clock } = fakeDisplay();
    const { result, rerender } = renderHook(
      ({ symbol }) => useTapeSubscription(symbol, { paneId: "p", enabled: true, clock }),
      { initialProps: { symbol: "BTCUSDT" } },
    );
    rerender({ symbol: "ETHUSDT" });
    expect(fake.specs.map((s) => s.ch)).toEqual(["trades.BTCUSDT", "trades.ETHUSDT"]);
    expect(result.current?.symbol).toBe("ETHUSDT");
    rerender({ symbol: "eth" });
    expect(result.current).toBeNull();
    expect(fake.client.consume).toHaveBeenCalledTimes(2);
  });

  it("never returns the previous symbol's feed on the render after a symbol change", () => {
    install();
    const { clock } = fakeDisplay();
    const seen: (string | undefined)[] = [];
    const { rerender } = renderHook(
      ({ symbol }) => {
        const feed = useTapeSubscription(symbol, { paneId: "p", enabled: true, clock });
        seen.push(feed?.symbol);
        return feed;
      },
      { initialProps: { symbol: "BTCUSDT" } },
    );
    seen.length = 0;
    rerender({ symbol: "ETHUSDT" });
    expect(seen).not.toContain("BTCUSDT");
    expect(seen.at(-1)).toBe("ETHUSDT");
  });

  it("lets an error from the client's consume surface instead of swallowing it", () => {
    const fake = install();
    fake.client.consume.mockImplementationOnce(() => {
      throw new Error("consume failed");
    });
    const { clock } = fakeDisplay();
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() =>
      renderHook(() => useTapeSubscription("BTCUSDT", { paneId: "p", enabled: true, clock })),
    ).toThrow("consume failed");
    quiet.mockRestore();
  });
});
