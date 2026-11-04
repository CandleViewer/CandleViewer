// E24-S03 (#778) slice 1: the funding pane's history state: loading, ready with its coverage word, failed
// keeping the last good series and time, unavailable, retry, and teardown.
import { describe, expect, it, vi } from "vitest";
import { startFundingFeed } from "../../../src/features/funding/fundingFeed";
import type {
  FundingCoverage,
  FundingHistoryOk,
  FundingHistoryRequest,
  FundingHistoryResult,
} from "../../../src/features/funding/history";
import { recordedSettled } from "./support/fundingFixtures";

const SETTLED = recordedSettled("BTCUSDT_8h").map((i) => ({
  tMs: Date.parse(i.t),
  rate: i.funding_rate,
}));
const covered = (noCoverage: boolean): FundingCoverage => ({ noCoverage, gaps: [] });
const ok = (over: Partial<FundingHistoryOk> = {}): FundingHistoryOk => ({
  kind: "ok",
  settled: SETTLED,
  intervalMinutes: 480,
  predicted: null,
  coverage: null,
  truncated: false,
  ...over,
});
const flush = async (): Promise<void> => {
  for (let i = 0; i < 3; i += 1) await Promise.resolve();
};

function start(symbol = "BTCUSDT", onFailed = vi.fn()) {
  const calls: { req: FundingHistoryRequest; resolve: (r: FundingHistoryResult) => void }[] = [];
  const loadHistory = (req: FundingHistoryRequest) =>
    new Promise<FundingHistoryResult>((resolve) => calls.push({ req, resolve }));
  const window = { fromMs: 0, toMs: 1 };
  const wall = { ms: 42 };
  const feed = startFundingFeed({ symbol, window, loadHistory, wallNow: () => wall.ms, onFailed });
  const answer = async (i: number, r: FundingHistoryResult) => {
    calls[i]?.resolve(r);
    await flush();
  };
  return { feed, calls, answer, onFailed, wall };
}

describe("funding feed", () => {
  it("refuses a symbol that is not a USDT perpetual", () => {
    expect(() => start("BTC-PERP")).toThrow(RangeError);
  });

  it("loads, then publishes the series, the coverage word and last_success_at", async () => {
    const { feed, calls, answer } = start();
    const listener = vi.fn();
    feed.subscribe(listener);
    expect(feed.getSnapshot().history.phase).toBe("loading");
    expect(calls[0]?.req).toMatchObject({ symbol: "BTCUSDT", fromMs: 0, toMs: 1 });
    await answer(0, ok({ coverage: covered(true) }));
    expect(feed.getSnapshot()).toMatchObject({
      history: { phase: "ready", empty: false, coverage: "not-recorded" },
      lastSuccessAtMs: 42,
    });
    expect(feed.getSnapshot().series.steps).toHaveLength(4);
    expect(listener).toHaveBeenCalled();
  });

  it("reads coverage that is not served as unknown, never as covered (BQ 6)", async () => {
    const { feed, answer } = start();
    await answer(0, ok({ settled: [], coverage: null }));
    expect(feed.getSnapshot().history).toEqual({
      phase: "ready",
      empty: true,
      coverage: "unknown",
      truncated: false,
    });
  });

  it("keeps the last good series and time on a failure and reports it once", async () => {
    const { feed, answer, onFailed, wall } = start();
    await answer(0, ok({ settled: [], coverage: covered(false) }));
    expect(feed.getSnapshot().history).toMatchObject({ empty: true, coverage: "covered" });
    feed.retry();
    wall.ms = 1_000;
    await answer(1, ok());
    expect(feed.getSnapshot().lastSuccessAtMs).toBe(1_000);
    feed.retry();
    expect(feed.getSnapshot().history.phase).toBe("loading");
    wall.ms = 9_000;
    await answer(2, { kind: "failed", status: 503, code: "service_unavailable" });
    expect(feed.getSnapshot()).toMatchObject({
      history: { phase: "failed", status: 503 },
      lastSuccessAtMs: 1_000,
    });
    expect(feed.getSnapshot().series.settled).toHaveLength(4);
    expect(onFailed).toHaveBeenCalledExactlyOnceWith(503, "service_unavailable");
  });

  it("clears the series when the instrument is unavailable", async () => {
    const { feed, answer } = start("SOLUSDT");
    await answer(0, { kind: "unavailable" });
    expect(feed.getSnapshot().history.phase).toBe("unavailable");
    expect(feed.getSnapshot().series.settled).toEqual([]);
  });

  it("turns a throwing or rejecting loader into a failure, never a pane stuck loading", async () => {
    const window = { fromMs: 0, toMs: 1 };
    const boom = (): never => {
      throw new Error("x");
    };
    const throwing = startFundingFeed({ symbol: "BTCUSDT", window, loadHistory: boom });
    const rejecting = startFundingFeed({
      symbol: "BTCUSDT",
      window,
      loadHistory: () => Promise.reject(new Error("x")),
    });
    await flush();
    expect(throwing.getSnapshot().history).toEqual({ phase: "failed", status: null });
    expect(rejecting.getSnapshot().history).toEqual({ phase: "failed", status: null });
  });

  it("drops a superseded read and stops cleanly: aborted, no listener called after stop", async () => {
    const { feed, calls, answer } = start();
    feed.retry();
    expect(calls[0]?.req.signal.aborted).toBe(true);
    await answer(0, ok());
    expect(feed.getSnapshot().history.phase).toBe("loading");
    const listener = vi.fn();
    feed.subscribe(listener);
    feed.stop();
    feed.stop();
    expect(calls[1]?.req.signal.aborted).toBe(true);
    await answer(1, ok());
    feed.retry();
    expect(listener).not.toHaveBeenCalled();
    expect(calls).toHaveLength(2);
  });
});
