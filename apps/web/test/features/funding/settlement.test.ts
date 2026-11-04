// E24-S03 (#778) slice 2, BQ 5: at the settlement the history polls `to = now` once, then backs off 1 / 2 / 4 /
// 8 s, at most five attempts, and appends the newly settled rate; no busy polling.
import { describe, expect, it, vi } from "vitest";
import { SETTLE_BACKOFF_MS, startFundingFeed } from "../../../src/features/funding/fundingFeed";
import type {
  FundingHistoryRequest,
  FundingHistoryResult,
} from "../../../src/features/funding/history";
import { recordedSettled } from "./support/fundingFixtures";

const ALL = recordedSettled("BTCUSDT_8h").map((i) => ({
  tMs: Date.parse(i.t),
  rate: i.funding_rate,
}));
const OLD = ALL.slice(0, 3);
const DEADLINE = ALL[3]?.tMs ?? 0;
const ok = (settled: typeof ALL): FundingHistoryResult => ({
  kind: "ok",
  settled,
  intervalMinutes: 480,
  coverage: null,
  truncated: false,
});

const failed: FundingHistoryResult = { kind: "failed", status: 503, code: null };
const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

function setup(answers: FundingHistoryResult[]) {
  const reqs: FundingHistoryRequest[] = [];
  const waits: number[] = [];
  const due: (() => void)[] = [];
  const clear = vi.fn();
  const loadHistory = vi.fn(async (req: FundingHistoryRequest) => {
    reqs.push(req);
    return answers.shift() ?? ok(OLD);
  });
  const feed = startFundingFeed({
    symbol: "BTCUSDT",
    window: { fromMs: OLD[0]?.tMs ?? 0, toMs: DEADLINE },
    loadHistory,
    now: () => DEADLINE + 250,
    timers: {
      setTimeout: (run, ms) => (waits.push(ms), due.push(run)),
      clearTimeout: clear,
    },
  });
  const step = async (): Promise<void> => {
    due.shift()?.();
    await flush();
  };
  /** The initial read answers, then the countdown reaches the deadline. */
  const settle = async (): Promise<void> => {
    await flush();
    feed.settle(DEADLINE);
    await flush();
  };
  return { feed, reqs, waits, step, clear, loadHistory, settle };
}

describe("settlement poll", () => {
  it("appends the newly settled rate on the first poll, read from the last settlement to now", async () => {
    const { feed, reqs, waits, settle } = setup([ok(OLD), ok(ALL.slice(2))]);
    await settle();
    expect(reqs[1]).toMatchObject({ fromMs: OLD[2]?.tMs, toMs: DEADLINE + 251 });
    expect(feed.getSnapshot().series.settled.map((p) => p.tMs)).toEqual(ALL.map((p) => p.tMs));
    expect(feed.getSnapshot().series.steps).toHaveLength(4);
    expect(waits).toEqual([]);
  });

  it("backs off 1, 2, 4 and 8 s and stops after five attempts", async () => {
    const { feed, waits, step, loadHistory, settle } = setup([ok(OLD)]);
    await settle();
    for (let i = 0; i < 6; i += 1) await step();
    expect(waits).toEqual([...SETTLE_BACKOFF_MS]);
    expect(loadHistory).toHaveBeenCalledTimes(1 + 5);
    expect(feed.getSnapshot().series.settled).toHaveLength(3);
  });

  it("keeps polling past a failure and stops when the settlement arrives", async () => {
    const { feed, waits, step, settle } = setup([ok(OLD), failed, ok(OLD), ok(ALL)]);
    await settle();
    await step();
    await step();
    expect(waits).toEqual([1_000, 2_000]);
    expect(feed.getSnapshot().series.settled).toHaveLength(4);
    expect(feed.getSnapshot().history).toMatchObject({ phase: "ready", empty: false });
  });

  it("appends the polled rate but keeps the retry band of a failed window (m2)", async () => {
    const { feed, settle } = setup([failed, ok(ALL)]);
    await settle();
    expect(feed.getSnapshot().history).toEqual({ phase: "failed", status: 503 });
    expect(feed.getSnapshot().series.settled).toHaveLength(4);
  });

  it("cancels a running poll on a newer settlement and on stop", async () => {
    const { feed, clear, settle } = setup([ok(OLD)]);
    await settle();
    feed.settle(DEADLINE);
    expect(clear).toHaveBeenCalledOnce();
    await flush();
    feed.stop();
    expect(clear).toHaveBeenCalledTimes(2);
    feed.settle(DEADLINE);
    expect(clear).toHaveBeenCalledTimes(2);
  });
});
