// E24-S08 (#783) slice 2: a failed source (US-DERIV-008 scenario 3): the failed state with `last_success_at`
// kept in the view model, the last values never blanked, the retry action, and the failure analytics.
import { describe, expect, it, vi } from "vitest";
import { startBasisFeed, type BasisClock } from "../../../src/features/basis/basisFeed";
import { fakeClient } from "../tape/fakeFeed";
import { recordedTickerItems, tickerDelta, tickerReset, tickerSnap } from "./support/basisFixtures";

const WALL = Date.parse("2026-10-21T09:14:02Z");
const first = recordedTickerItems()[0];
if (first === undefined) throw new Error("ticker fixture");

function display() {
  const requested = new Map<number, () => void>();
  let id = 0;
  let nowMs = 0;
  const clock: BasisClock = {
    raf: (cb) => (requested.set(++id, () => cb(nowMs)), id),
    caf: (h) => void requested.delete(h),
    now: () => nowMs,
    wallNow: () => WALL + nowMs,
  };
  return {
    clock,
    frame: (advanceMs = 16) => {
      nowMs += advanceMs;
      const due = [...requested.values()];
      requested.clear();
      for (const cb of due) cb();
    },
  };
}

function start() {
  const fake = fakeClient();
  const d = display();
  const analytics = {
    sourceToggled: vi.fn(),
    sourceFailed: vi.fn(),
    retryShown: vi.fn(),
    retryClicked: vi.fn(),
  };
  const feed = startBasisFeed(fake.client, {
    symbol: "BTCUSDT",
    paneId: "basis-1",
    clock: d.clock,
    analytics,
  });
  const handle = () => {
    const h = fake.handles[fake.handles.length - 1];
    if (h === undefined) throw new Error("handle");
    return h;
  };
  return { fake, d, feed, handle, analytics };
}

describe("basis feed: a failed source", () => {
  it("is ok while live and failed when the topic is revoked, keeping the last values", () => {
    const { d, feed, handle } = start();
    handle().status = "live";
    handle().queue.push(tickerSnap([first]));
    d.frame();
    expect(feed.getSnapshot().source).toEqual({ state: "ok" });
    handle().status = "revoked";
    d.frame();
    const snap = feed.getSnapshot();
    expect(snap.source).toEqual({ state: "failed", status: "revoked", lastSuccessAtMs: WALL + 16 });
    expect(snap.latest?.last).toBe("82751.20"); // never blank
  });

  it("keeps last_success_at at the last accepted item, not the failure time", () => {
    const { d, feed, handle } = start();
    handle().status = "live";
    handle().queue.push(tickerSnap([first]));
    d.frame();
    handle().queue.push(tickerDelta([{ ...first, ts_ms: first.ts_ms + 100 }]));
    d.frame(1_000);
    handle().status = "revoked";
    d.frame(30_000);
    expect(feed.getSnapshot().source).toMatchObject({
      state: "failed",
      lastSuccessAtMs: WALL + 16 + 1_000,
    });
  });

  it("maps a stale topic to the stale chip (t2), never to the failed state", () => {
    const { d, feed, handle } = start();
    handle().status = "live";
    handle().queue.push(tickerSnap([first]));
    d.frame();
    handle().status = "stale";
    d.frame();
    expect(feed.getSnapshot().source).toEqual({ state: "ok" });
    expect(feed.getSnapshot().stale.tier).toBe("t2");
    expect(feed.getSnapshot().latest?.last).toBe("82751.20");
  });

  it("accepts an older-ts snapshot after a reset, keeping the shown values meanwhile", () => {
    const { d, feed, handle } = start();
    handle().status = "live";
    handle().queue.push(tickerSnap([{ ...first, ts_ms: first.ts_ms + 5_000 }]));
    d.frame();
    handle().queue.push(tickerReset);
    d.frame(1_000);
    expect(feed.getSnapshot().latest?.tsMs).toBe(first.ts_ms + 5_000);
    handle().queue.push(tickerSnap([{ ...first, last_price: "82700.00" }]));
    d.frame(1_000);
    expect(feed.getSnapshot().latest).toMatchObject({ tsMs: first.ts_ms, last: "82700.00" });
  });

  it("accepts an older-ts snapshot on the new subscription after retry", () => {
    const { d, feed, handle } = start();
    handle().status = "live";
    handle().queue.push(tickerSnap([{ ...first, ts_ms: first.ts_ms + 5_000 }]));
    d.frame();
    feed.retry();
    expect(feed.getSnapshot().latest?.tsMs).toBe(first.ts_ms + 5_000);
    handle().status = "live";
    handle().queue.push(tickerSnap([first]));
    d.frame(1_000);
    expect(feed.getSnapshot().latest?.tsMs).toBe(first.ts_ms);
  });

  it("has a null last_success_at when nothing ever arrived", () => {
    const { d, feed, handle } = start();
    handle().status = "revoked";
    d.frame();
    expect(feed.getSnapshot().source).toEqual({
      state: "failed",
      status: "revoked",
      lastSuccessAtMs: null,
    });
  });

  it("reports the failure and one retry-state render per entry, not per frame", () => {
    const { d, handle, analytics } = start();
    handle().status = "revoked";
    d.frame();
    d.frame();
    d.frame();
    expect(analytics.sourceFailed).toHaveBeenCalledTimes(1);
    expect(analytics.sourceFailed).toHaveBeenCalledWith("BTCUSDT", "revoked");
    expect(analytics.retryShown).toHaveBeenCalledTimes(1);
  });

  it("retry releases the old subscription, takes a new one and recovers", () => {
    const { fake, d, feed, handle, analytics } = start();
    handle().status = "revoked";
    d.frame();
    const old = handle();
    feed.retry();
    expect(old.release).toHaveBeenCalledTimes(1);
    expect(fake.handles).toHaveLength(2);
    expect(analytics.retryClicked).toHaveBeenCalledWith("BTCUSDT");
    handle().status = "live";
    handle().queue.push(tickerSnap([first]));
    d.frame();
    expect(feed.getSnapshot().source).toEqual({ state: "ok" });
    feed.stop();
    expect(handle().release).toHaveBeenCalledTimes(1);
    expect(old.release).toHaveBeenCalledTimes(1);
  });

  it("does not retry after stop", () => {
    const { fake, feed } = start();
    feed.stop();
    feed.retry();
    expect(fake.handles).toHaveLength(1);
  });
});
