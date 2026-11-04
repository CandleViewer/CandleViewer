// E24-S07 (#782) slice 2: the read cadence (BQ 6): nothing while off, one read on enable and per symbol change, a
// re-read only after new prints and at most every 5 s, stale after a failed refresh, nothing drawn after a refusal,
// and the teardown: unmount aborts the read in flight and clears the timer.
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ByPriceRead,
  ByPriceRequest,
} from "../../../../../src/features/derivatives/liquidations/byPrice/byPriceRead";
import { EXAMPLE } from "../../../../../src/features/derivatives/liquidations/byPrice/samples";
import {
  MIN_INTERVAL_MS,
  useLiquidationsByPrice,
  type ByPriceOptions,
} from "../../../../../src/features/derivatives/liquidations/byPrice/useLiquidationsByPrice";

const OK: ByPriceRead = { kind: "ok", answer: EXAMPLE };

function mount(over: Partial<ByPriceOptions> = {}, reads: ByPriceRead[] = [OK]) {
  const calls: ByPriceRequest[] = [];
  const read = vi.fn((req: ByPriceRequest): Promise<ByPriceRead> => {
    calls.push(req);
    return Promise.resolve(reads[Math.min(calls.length - 1, reads.length - 1)] ?? OK);
  });
  const analytics = { toggled: vi.fn(), readFailed: vi.fn() };
  const props: ByPriceOptions = { symbol: "BTCUSDT", enabled: true, printSeq: 0, read, analytics };
  const hook = renderHook((p: ByPriceOptions) => useLiquidationsByPrice(p), {
    initialProps: { ...props, ...over },
  });
  const set = (o: Partial<ByPriceOptions>): void => hook.rerender({ ...props, ...over, ...o });
  return { calls, read, analytics, set, hook };
}

const flush = async (ms = 0): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

describe("useLiquidationsByPrice", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(EXAMPLE.to));
  });
  afterEach(() => vi.useRealTimers());

  it("reads nothing while off (the default)", async () => {
    const { read, hook } = mount({ enabled: false });
    await flush(60_000);
    expect(read).not.toHaveBeenCalled();
    expect(hook.result.current).toMatchObject({ phase: "off", layer: null });
  });

  it("reads once on enable, serves the layer, and never again without new prints", async () => {
    const { calls, hook } = mount();
    expect(hook.result.current.phase).toBe("loading");
    await flush();
    expect(hook.result.current.phase).toBe("ready");
    expect(hook.result.current.layer?.coverage.kind).toBe("partial");
    await flush(60_000);
    expect(calls).toHaveLength(1);
  });

  it("re-reads only after new prints, at most once every 5 s", async () => {
    const { calls, set } = mount();
    await flush();
    set({ printSeq: 1 });
    set({ printSeq: 2 });
    await flush(MIN_INTERVAL_MS - 1);
    expect(calls).toHaveLength(1);
    await flush(1);
    expect(calls).toHaveLength(2);
    set({ printSeq: 3 });
    await flush(MIN_INTERVAL_MS * 5);
    expect(calls).toHaveLength(3);
  });

  it("reads again at once on a symbol change, aborting the old symbol's read", async () => {
    const { calls, set, hook } = mount();
    await flush();
    set({ symbol: "ETHUSDT" });
    expect(hook.result.current.phase).toBe("loading");
    await flush();
    expect(calls.map((c) => c.symbol)).toEqual(["BTCUSDT", "ETHUSDT"]);
    expect(calls[0]?.signal.aborted).toBe(true);
  });

  it("keeps the layer and marks it stale when a refresh fails", async () => {
    const fail: ByPriceRead = { kind: "failed", status: 503, code: "unavailable" };
    const { set, hook, analytics } = mount({}, [OK, fail]);
    await flush();
    set({ printSeq: 1 });
    await flush(MIN_INTERVAL_MS);
    expect(hook.result.current).toMatchObject({ phase: "ready", stale: true });
    expect(analytics.readFailed).toHaveBeenCalledWith("BTCUSDT", 503, "unavailable");
  });

  it("draws nothing after a refused answer, and Retry reads again", async () => {
    const refused: ByPriceRead = { kind: "refused", code: "estimated_missing" };
    const { calls, hook, analytics } = mount({}, [refused, OK]);
    await flush();
    expect(hook.result.current).toMatchObject({ phase: "refused", layer: null });
    expect(analytics.readFailed).toHaveBeenCalledWith("BTCUSDT", 200, "estimated_missing");
    act(() => hook.result.current.retry());
    await flush();
    expect(calls).toHaveLength(2);
    expect(hook.result.current.phase).toBe("ready");
  });

  it("is failed when the first read throws", async () => {
    const { hook } = mount({ read: () => Promise.reject(new Error("boom")) });
    await flush();
    expect(hook.result.current).toMatchObject({ phase: "failed", layer: null, stale: false });
  });

  it("aborts the read and clears the timer on unmount, and stops when switched off", async () => {
    const first = mount();
    await flush();
    first.set({ printSeq: 1 });
    expect(vi.getTimerCount()).toBe(1);
    first.hook.unmount();
    expect(vi.getTimerCount()).toBe(0);
    expect(first.calls[0]?.signal.aborted).toBe(true);
    const second = mount();
    await flush();
    second.set({ enabled: false, printSeq: 5 });
    await flush(MIN_INTERVAL_MS * 2);
    expect(second.calls).toHaveLength(1);
    expect(second.hook.result.current.phase).toBe("off");
  });
});
