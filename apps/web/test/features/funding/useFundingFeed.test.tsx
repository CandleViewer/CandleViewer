// E24-S03 (#778) slice 1: the hook reads once per symbol and window, aborts the read it replaces and the one
// in flight on unmount (every subscription has a teardown test, rules/30), and starts none for a non-perpetual;
// `useFundingSnapshot` follows the feed; a failed read sends the ticket's one analytics event.
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createFundingAnalytics } from "../../../src/features/funding/analytics";
import {
  INITIAL_FUNDING_SNAPSHOT,
  useFundingSnapshot,
} from "../../../src/features/funding/fundingFeed";
import type {
  FundingHistoryRequest,
  FundingHistoryResult,
} from "../../../src/features/funding/history";
import { useFundingFeed } from "../../../src/features/funding/useFundingFeed";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore";

const flush = async (): Promise<void> => {
  for (let i = 0; i < 3; i += 1) await Promise.resolve();
};

describe("useFundingFeed", () => {
  it("restarts on a symbol change, aborts on unmount and never serves a non-perpetual", () => {
    const calls: FundingHistoryRequest[] = [];
    const loadHistory = vi.fn((req: FundingHistoryRequest) => {
      calls.push(req);
      return new Promise<FundingHistoryResult>(() => undefined);
    });
    const options = { fromMs: 0, toMs: 1, loadHistory };
    const { result, rerender, unmount } = renderHook(
      ({ symbol }: { symbol: string }) => useFundingFeed(symbol, options),
      { initialProps: { symbol: "BTCUSDT" } },
    );
    rerender({ symbol: "BTCUSDT" });
    expect(calls).toHaveLength(1);
    rerender({ symbol: "ETHUSDT" });
    expect(result.current?.symbol).toBe("ETHUSDT");
    expect(calls[0]?.signal.aborted).toBe(true);
    unmount();
    expect(calls[1]?.signal.aborted).toBe(true);
    const bad = renderHook(() => useFundingFeed("BTC-PERP", options));
    expect(bad.result.current).toBeNull();
    expect(calls).toHaveLength(2);
  });

  it("follows the feed's snapshot, and the initial one with no feed", async () => {
    let answer: ((r: FundingHistoryResult) => void) | undefined;
    const loadHistory = () => new Promise<FundingHistoryResult>((resolve) => (answer = resolve));
    const options = { fromMs: 0, toMs: 1, loadHistory, wallNow: () => 7 };
    const { result } = renderHook(() => useFundingSnapshot(useFundingFeed("BTCUSDT", options)));
    expect(result.current.history.phase).toBe("loading");
    await act(async () => {
      answer?.({ kind: "unavailable" });
      await flush();
    });
    expect(result.current.history.phase).toBe("unavailable");
    expect(renderHook(() => useFundingSnapshot(null)).result.current).toBe(
      INITIAL_FUNDING_SNAPSHOT,
    );
  });

  it("sends funding.history_failed with the symbol, status and code, never a value", async () => {
    const report = vi.fn();
    const loadHistory = () =>
      Promise.resolve<FundingHistoryResult>({
        kind: "failed",
        status: 503,
        code: "service_unavailable",
      });
    const options = { fromMs: 0, toMs: 1, loadHistory, analytics: createFundingAnalytics(report) };
    renderHook(() => useFundingFeed("BTCUSDT", options));
    await act(flush);
    expect(report).toHaveBeenCalledExactlyOnceWith({
      name: "funding.history_failed",
      symbol: "BTCUSDT",
      status: 503,
      code: "service_unavailable",
    });
  });

  it("dispatches on the app's analytics seam by default", () => {
    const seen = vi.fn();
    const listener = (e: Event) => seen((e as CustomEvent).detail);
    window.addEventListener(THEME_ANALYTICS_EVENT, listener);
    createFundingAnalytics().historyFailed("ETHUSDT", null, null);
    window.removeEventListener(THEME_ANALYTICS_EVENT, listener);
    expect(seen).toHaveBeenCalledExactlyOnceWith({
      name: "funding.history_failed",
      symbol: "ETHUSDT",
      status: null,
      code: null,
    });
  });
});
