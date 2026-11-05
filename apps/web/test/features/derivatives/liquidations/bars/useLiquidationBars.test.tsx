// E24-S06 (#781) slice 1: the bars' read lifecycle — one read per key, one per bar close on a fake clock, stale
// after a failed refresh, a coverage that arrives late costs no second read, nothing runs while disabled, and the
// teardown aborts the read and clears the timer.
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LiqCoverage } from "../../../../../src/features/derivatives/liquidations/history";
import type {
  BarsRead,
  BarsRequest,
} from "../../../../../src/features/derivatives/liquidations/bars/barsRead";
import {
  nextRefreshMs,
  REFRESH_GRACE_MS,
  useLiquidationBars,
  type LiqBarsOptions,
} from "../../../../../src/features/derivatives/liquidations/bars/useLiquidationBars";
import {
  COVERAGE,
  HOUR,
  NOW,
  SERVED_LONG,
  SERVED_SHORT,
} from "../../../../../src/features/derivatives/liquidations/bars/samples";

const OK: BarsRead = { kind: "ok", long: SERVED_LONG, short: SERVED_SHORT, malformed: 0 };
const FAIL: BarsRead = { kind: "failed", status: 503, code: null, detail: null };

function setup(over: Partial<LiqBarsOptions> = {}, reads: BarsRead[] = [OK]) {
  const calls: BarsRequest[] = [];
  const read = vi.fn((req: BarsRequest): Promise<BarsRead> => {
    calls.push(req);
    return Promise.resolve(reads[Math.min(calls.length - 1, reads.length - 1)] ?? OK);
  });
  const props: LiqBarsOptions = {
    symbol: "BTCUSDT",
    param: "60",
    coverage: COVERAGE,
    minNotionalUsd: "0",
    serverThreshold: false,
    read,
    now: () => Date.now(),
    ...over,
  };
  return { calls, read, props };
}

const flush = async (): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
};

describe("useLiquidationBars", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it("starts loading, then serves the masked bars of one read per side pair", async () => {
    const { props, calls } = setup();
    const { result } = renderHook(() => useLiquidationBars(props));
    expect(result.current.phase).toBe("loading");
    await flush();
    expect(result.current.phase).toBe("ready");
    expect(calls).toHaveLength(1);
    expect(result.current.bars.map((b) => b.state)).toEqual([
      "unknown",
      "unknown",
      "unknown",
      "zero",
      "recorded",
    ]);
    expect(result.current.window?.toMs).toBe(NOW);
    expect(result.current.loadedAtMs).toBe(NOW);
    expect(result.current.stale).toBe(false);
  });

  it("holds the raw read and shows no bars until coverage is known, then masks without a second read", async () => {
    const { props, calls } = setup({ coverage: null });
    const { result, rerender } = renderHook((p: LiqBarsOptions) => useLiquidationBars(p), {
      initialProps: props,
    });
    await flush();
    expect(result.current.phase).toBe("ready");
    expect(result.current.bars).toEqual([]);
    const late: LiqCoverage = COVERAGE;
    rerender({ ...props, coverage: late });
    expect(result.current.bars).toHaveLength(5);
    expect(calls).toHaveLength(1);
  });

  it("refreshes once after each bar closes", async () => {
    const { props, calls } = setup();
    renderHook(() => useLiquidationBars(props));
    await flush();
    const toClose = HOUR - (NOW % HOUR) + REFRESH_GRACE_MS;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(toClose - 1);
    });
    expect(calls).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(calls).toHaveLength(2);
    expect(nextRefreshMs(Date.parse("2026-10-21T11:59:59.900Z"), HOUR)).toBe(
      REFRESH_GRACE_MS + 100,
    );
  });

  it("keeps the last good bars and marks them stale when a refresh fails; the next good read clears it", async () => {
    const { props } = setup({}, [OK, FAIL, OK]);
    const { result } = renderHook(() => useLiquidationBars(props));
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HOUR);
    });
    expect(result.current.stale).toBe(true);
    expect(result.current.phase).toBe("ready");
    expect(result.current.bars).toHaveLength(5);
    expect(result.current.error).toEqual({ status: 503, code: null, detail: null });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HOUR);
    });
    expect(result.current.stale).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("fails on a first read that fails, and Retry reads again", async () => {
    const { props, calls } = setup({}, [FAIL, OK]);
    const { result } = renderHook(() => useLiquidationBars(props));
    await flush();
    expect(result.current.phase).toBe("failed");
    expect(result.current.bars).toEqual([]);
    act(() => result.current.retry());
    await flush();
    expect(calls).toHaveLength(2);
    expect(result.current.phase).toBe("ready");
  });

  it("starts from loading on a symbol or threshold change: another key's bars are never shown", async () => {
    const { props, calls } = setup({ serverThreshold: true });
    const { result, rerender } = renderHook((p: LiqBarsOptions) => useLiquidationBars(p), {
      initialProps: props,
    });
    await flush();
    rerender({ ...props, minNotionalUsd: "50000" });
    expect(result.current.phase).toBe("loading");
    expect(result.current.bars).toEqual([]);
    await flush();
    expect(calls.map((c) => c.minNotionalUsd)).toEqual(["0", "50000"]);
    rerender({ ...props, minNotionalUsd: "50000", symbol: "ETHUSDT" });
    expect(result.current.phase).toBe("loading");
  });

  it("does not read again, nor blank, when the threshold changes and the server does not apply it (BQ-1)", async () => {
    const { props, calls } = setup();
    const { result, rerender } = renderHook((p: LiqBarsOptions) => useLiquidationBars(p), {
      initialProps: props,
    });
    await flush();
    rerender({ ...props, minNotionalUsd: "50000" });
    await flush();
    expect(result.current.phase).toBe("ready");
    expect(result.current.bars).toHaveLength(5);
    expect(calls).toHaveLength(1);
  });

  it("does not bring back an old key's error while another key loads (A fails, B, back to A)", async () => {
    let release: (r: BarsRead) => void = () => undefined;
    const read = vi
      .fn<(req: BarsRequest) => Promise<BarsRead>>()
      .mockResolvedValueOnce(FAIL) // A fails
      .mockImplementationOnce(() => new Promise<BarsRead>((r) => (release = r))); // B waits
    const { props } = setup({ read });
    const { result, rerender } = renderHook((p: LiqBarsOptions) => useLiquidationBars(p), {
      initialProps: props,
    });
    await flush();
    expect(result.current.phase).toBe("failed");
    rerender({ ...props, symbol: "ETHUSDT" });
    expect(result.current.phase).toBe("loading");
    read.mockResolvedValueOnce(OK);
    rerender({ ...props, symbol: "BTCUSDT" }); // back to A while B is still loading
    expect(result.current.phase).toBe("loading");
    expect(result.current.error).toBeNull();
    release(OK);
    await flush();
    expect(result.current.phase).toBe("ready");
  });

  it("shows no old bars as fresh after a mode with no read: they are cleared on disable", async () => {
    const { props, calls } = setup();
    const { result, rerender } = renderHook((p: LiqBarsOptions) => useLiquidationBars(p), {
      initialProps: props,
    });
    await flush();
    rerender({ ...props, enabled: false });
    expect(result.current.phase).toBe("loading");
    expect(result.current.bars).toEqual([]);
    rerender({ ...props, enabled: true });
    expect(result.current.phase).toBe("loading");
    await flush();
    expect(calls).toHaveLength(2);
    expect(result.current.phase).toBe("ready");
  });

  it("treats a read that throws as a failed read and still re-arms the next one", async () => {
    const read = vi
      .fn<(req: BarsRequest) => Promise<BarsRead>>()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue(OK);
    const { props } = setup({ read });
    const { result } = renderHook(() => useLiquidationBars(props));
    await flush();
    expect(result.current.phase).toBe("failed");
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HOUR);
    });
    expect(result.current.phase).toBe("ready");
  });

  it("stamps the bars with the time the read landed, not the time it started", async () => {
    const read = vi.fn((): Promise<BarsRead> => new Promise((r) => setTimeout(() => r(OK), 7_000)));
    const { props } = setup({ read });
    const { result } = renderHook(() => useLiquidationBars(props));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(7_000);
    });
    expect(result.current.loadedAtMs).toBe(NOW + 7_000);
  });

  it("reads nothing while disabled, and an unknown interval is a failure without a read", async () => {
    const off = setup({ enabled: false });
    renderHook(() => useLiquidationBars(off.props));
    await flush();
    expect(off.read).not.toHaveBeenCalled();
    const odd = setup({ param: "7" });
    const { result } = renderHook(() => useLiquidationBars(odd.props));
    await flush();
    expect(odd.read).not.toHaveBeenCalled();
    expect(result.current.phase).toBe("failed");
    expect(result.current.error?.code).toBe("unsupported_interval");
  });

  it("aborts the read and clears the timer on unmount", async () => {
    const { props, calls } = setup();
    const { unmount } = renderHook(() => useLiquidationBars(props));
    await flush();
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(calls[0]?.signal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("drops a read that lands after unmount", async () => {
    let resolve: (r: BarsRead) => void = () => undefined;
    const read = vi.fn(() => new Promise<BarsRead>((r) => (resolve = r)));
    const { props } = setup({ read });
    const { result, unmount } = renderHook(() => useLiquidationBars(props));
    unmount();
    resolve(OK);
    await flush();
    expect(result.current.phase).toBe("loading");
    expect(vi.getTimerCount()).toBe(0);
  });
});
