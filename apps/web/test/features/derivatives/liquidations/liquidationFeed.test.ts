// E24-S05 (#780): the feed loop — the subscription options, the rAF drain into the 250 ms coalescer (never a
// publish per message), the bounded rows under a cascade, the snapshot's dedupe, teardown (slice 1); the one
// backfill read merged under the live prints, its failure and retry, and its abort on stop (slice 2).
import { describe, expect, it, vi } from "vitest";
import type {
  LiqHistoryRequest,
  LiqHistoryResult,
} from "../../../../src/features/derivatives/liquidations/history";
import {
  startLiquidationFeed,
  VIEW_ROWS,
  type LiqFeedOptions,
} from "../../../../src/features/derivatives/liquidations/liquidationFeed";
import { fakeClient, fakeDisplay } from "../../tape/fakeFeed";
import { burst, delta, DESIGN, EXAMPLE, reset, snap } from "./liqFrames";

const WINDOW = {
  fromMs: Date.parse("2026-09-14T10:00:00Z"),
  toMs: Date.parse("2026-10-21T10:00:00Z"),
};
const never = (): Promise<LiqHistoryResult> => new Promise(() => undefined);
/** Lets the read's promise chain run (no timers, no sleep). */
const settle = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

function start(over: Partial<LiqFeedOptions> = {}, stepMs = 50) {
  const fake = fakeClient();
  const d = fakeDisplay(stepMs);
  const feed = startLiquidationFeed(fake.client, {
    symbol: "BTCUSDT",
    paneId: "liq-1",
    window: WINDOW,
    loadHistory: never,
    clock: { ...d.clock, wallNow: () => Date.parse("2026-10-21T09:14:02Z") },
    ...over,
  });
  const handle = fake.handles[0];
  if (handle === undefined) throw new Error("no handle");
  const published = vi.fn();
  feed.subscribe(published);
  return { ...fake, d, feed, handle, published };
}

describe("startLiquidationFeed", () => {
  it("subscribes liquidations.{symbol} with cluster_window_ms 0 and no filter by default (BQ 2)", () => {
    const { specs, feed } = start();
    expect(specs).toEqual([
      {
        ch: "liquidations.BTCUSDT",
        opts: { cluster_window_ms: 0 },
        paneId: "liq-1",
        priority: "other",
      },
    ]);
    expect(feed.getSnapshot().minNotionalUsd).toBeNull();
  });

  it("sends min_notional_usd as the subscription option and states it", () => {
    const { specs, feed } = start({ minNotionalUsd: "50000" });
    expect(specs[0]?.opts).toEqual({ cluster_window_ms: 0, min_notional_usd: "50000" });
    expect(feed.getSnapshot().minNotionalUsd).toBe("50000");
  });

  it("refuses a symbol that is not a USDT perpetual, a malformed filter and an empty window", () => {
    expect(() => start({ symbol: "BTC-USD" })).toThrow(RangeError);
    expect(() => start({ minNotionalUsd: "-5" })).toThrow(RangeError);
    expect(() => start({ window: { fromMs: 5, toMs: 5 } })).toThrow(RangeError);
  });

  it("publishes a delta only once its 250 ms bucket closes, newest first", () => {
    const { d, handle, feed, published } = start();
    handle.status = "live";
    handle.queue.push(delta([EXAMPLE]), delta([DESIGN]));
    d.frame(); // t = 50: read, bucket 0 open
    expect(feed.getSnapshot().rows).toHaveLength(0);
    const before = published.mock.calls.length;
    d.frame(); // 100
    d.frame(); // 150
    d.frame(); // 200
    expect(published.mock.calls.length).toBe(before); // nothing per frame while the bucket is open
    d.frame(); // 250: flushed
    const rows = feed.getSnapshot().rows;
    expect(rows.map((r) => r.price)).toEqual(["82751.20", "62880.00"]);
    expect(rows[0]?.side).toBe("long");
  });

  it("keeps rows at 40 and the ring at its bound during a 500 prints/s cascade for 10 s", () => {
    const { d, handle, feed, published } = start({}, 16);
    handle.status = "live";
    const t0 = EXAMPLE.ts_ms;
    for (let push = 0; push < 20; push += 1) {
      handle.queue.push(delta(burst(250, EXAMPLE, t0 + push * 500)));
      for (let f = 0; f < 32; f += 1) d.frame(); // ~500 ms of frames
    }
    const snapshot = feed.getSnapshot();
    expect(snapshot.rows).toHaveLength(VIEW_ROWS);
    expect(feed.metrics().held).toBe(1_000);
    expect(snapshot.newestSeq).toBe(4_999);
    expect(published.mock.calls.length).toBeLessThanOrEqual(40 * 2 + 4); // per bucket, never per print
  });

  it("shows the burst rate of the last push window", () => {
    const { d, handle, feed } = start({}, 50);
    handle.status = "live";
    handle.queue.push(delta(burst(620)));
    d.frame(); // 50: bucket 0
    for (let f = 0; f < 5; f += 1) d.frame(); // 300: bucket 1
    expect(feed.getSnapshot().ratePerSec).toBe(1_240);
    for (let f = 0; f < 10; f += 1) d.frame(); // 800
    expect(feed.getSnapshot().ratePerSec).toBe(0);
  });

  it("drops a resubscribe snapshot's replay at or before what it holds, after a reset", () => {
    const { d, handle, feed } = start();
    handle.status = "live";
    handle.queue.push(snap([EXAMPLE, DESIGN]));
    for (let f = 0; f < 6; f += 1) d.frame();
    handle.queue.push(reset(), snap([EXAMPLE, DESIGN, { ...DESIGN, ts_ms: DESIGN.ts_ms + 1 }]));
    for (let f = 0; f < 6; f += 1) d.frame();
    expect(feed.getSnapshot().rows.map((r) => r.tsMs)).toEqual([
      DESIGN.ts_ms + 1,
      DESIGN.ts_ms,
      EXAMPLE.ts_ms,
    ]);
    expect(feed.getSnapshot().ratePerSec).toBe(0); // a replay is not a burst
  });

  it("publishes a status change at once", () => {
    const { d, handle, feed } = start();
    d.frame();
    expect(feed.getSnapshot().feed).toBe("pending");
    handle.status = "resyncing";
    d.frame();
    expect(feed.getSnapshot().feed).toBe("resyncing");
  });

  it("releases the topic, cancels the frame and stops publishing on stop (idempotent)", () => {
    const { d, handle, feed, published } = start();
    feed.stop();
    feed.stop();
    expect(handle.release).toHaveBeenCalledTimes(1);
    expect(d.pending()).toBe(0);
    handle.queue.push(delta([EXAMPLE]));
    d.frame();
    expect(published).not.toHaveBeenCalled();
  });

  it("counts malformed items in its metrics", () => {
    const { d, handle, feed } = start();
    handle.queue.push(delta([{ ...EXAMPLE, side: "up" }]));
    d.frame();
    expect(feed.metrics().malformed).toBe(1);
  });

  it("reads the window once, with the filter, and merges the recorded prints under the live ones", async () => {
    const requests: LiqHistoryRequest[] = [];
    let resolve: (r: LiqHistoryResult) => void = () => undefined;
    const loadHistory = vi.fn(
      (r: LiqHistoryRequest) =>
        new Promise<LiqHistoryResult>((ok) => {
          requests.push(r);
          resolve = ok;
        }),
    );
    const { d, handle, feed } = start({ loadHistory, minNotionalUsd: "50000" });
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({ ...WINDOW, minNotionalUsd: "50000", keep: 1_000 });
    handle.status = "live";
    // a live print the read also returns (same time), and one after it
    const sameAsRest = { ...DESIGN };
    const newer = { ...DESIGN, ts_ms: DESIGN.ts_ms + 5 };
    handle.queue.push(delta([sameAsRest, newer]));
    d.frame();
    resolve({
      kind: "ok",
      prints: [EXAMPLE, DESIGN].map((w) => ({
        tsMs: w.ts_ms,
        side: "long" as const,
        price: w.price,
        size: w.size,
        notionalUsd: w.notional_usd ?? null,
        clusterSize: w.cluster_size ?? 1,
      })),
      coverage: { firstAvailableMs: 1, coveredFromMs: 2, coveredToMs: 3, noCoverage: false },
      truncated: false,
      malformed: 0,
    });
    await settle();
    for (let f = 0; f < 6; f += 1) d.frame();
    const snapshot = feed.getSnapshot();
    expect(snapshot.rows.map((r) => r.tsMs)).toEqual([newer.ts_ms, DESIGN.ts_ms, EXAMPLE.ts_ms]);
    expect(snapshot.history).toEqual({
      phase: "ready",
      coverage: { firstAvailableMs: 1, coveredFromMs: 2, coveredToMs: 3, noCoverage: false },
      truncated: false,
    });
    expect(snapshot.window).toEqual(WINDOW);
  });

  it("keeps streaming when the read fails, and retries with last_success_at", async () => {
    const results: LiqHistoryResult[] = [
      {
        kind: "ok",
        prints: [],
        coverage: {
          firstAvailableMs: null,
          coveredFromMs: null,
          coveredToMs: null,
          noCoverage: true,
        },
        truncated: false,
        malformed: 0,
      },
      { kind: "failed", status: 500, code: null },
    ];
    const loadHistory = vi.fn(async () => results.shift() ?? never());
    const { d, feed, handle } = start({ loadHistory });
    await settle();
    d.frame();
    expect(feed.getSnapshot().history.phase).toBe("ready");
    feed.retry();
    await settle();
    handle.status = "live";
    handle.queue.push(delta([DESIGN]));
    for (let f = 0; f < 6; f += 1) d.frame();
    expect(feed.getSnapshot().history).toEqual({
      phase: "failed",
      status: 500,
      lastSuccessAtMs: Date.parse("2026-10-21T09:14:02Z"),
    });
    expect(feed.getSnapshot().rows).toHaveLength(1);
    expect(loadHistory).toHaveBeenCalledTimes(2);
  });

  it("aborts the read on stop and ignores its late answer", async () => {
    let signal: AbortSignal | undefined;
    let resolve: (r: LiqHistoryResult) => void = () => undefined;
    const loadHistory = (r: LiqHistoryRequest) =>
      new Promise<LiqHistoryResult>((ok) => {
        signal = r.signal;
        resolve = ok;
      });
    const { feed, published } = start({ loadHistory });
    feed.stop();
    expect(signal?.aborted).toBe(true);
    resolve({ kind: "failed", status: 500, code: null });
    await settle();
    feed.retry();
    expect(published).not.toHaveBeenCalled();
    expect(feed.getSnapshot().history.phase).toBe("loading");
  });
});
