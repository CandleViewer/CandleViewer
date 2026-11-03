// E24-S08 (#783) slice 1: the basis feed loop: rAF coalescing, the <= 1 Hz value publish, stale T1 / T2,
// and teardown. Frames from the recorded capture (C-13.5).
import { describe, expect, it, vi } from "vitest";
import {
  PUBLISH_INTERVAL_MS,
  staleTier,
  startBasisFeed,
  type BasisClock,
} from "../../../src/features/basis/basisFeed";
import { fakeClient } from "../tape/fakeFeed";
import { recordedTickerItems, tickerDelta, tickerReset, tickerSnap } from "./support/basisFixtures";

const ITEMS = recordedTickerItems();
const at = (i: number, ts?: number) => {
  const it = ITEMS[i % ITEMS.length];
  if (it === undefined) throw new Error("fixture");
  return ts === undefined ? it : { ...it, ts_ms: ts };
};

function display() {
  const requested = new Map<number, () => void>();
  let id = 0;
  let nowMs = 0;
  const clock: BasisClock = {
    raf: (cb) => (requested.set(++id, () => cb(nowMs)), id),
    caf: (h) => void requested.delete(h),
    now: () => nowMs,
    wallNow: () => Date.parse("2026-10-21T09:14:02Z") + nowMs,
  };
  return {
    clock,
    pending: () => requested.size,
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
  const feed = startBasisFeed(fake.client, {
    symbol: "BTCUSDT",
    paneId: "basis-1",
    clock: d.clock,
  });
  const handle = fake.handles[0];
  if (handle === undefined) throw new Error("handle");
  return { fake, d, feed, handle };
}

describe("startBasisFeed", () => {
  it("subscribes to ticker.{symbol} once and rejects a non-USDT symbol", () => {
    const { fake } = start();
    expect(fake.specs).toEqual([{ ch: "ticker.BTCUSDT", paneId: "basis-1", priority: "other" }]);
    expect(() => startBasisFeed(fakeClient().client, { symbol: "BTCUSD", paneId: "p" })).toThrow(
      RangeError,
    );
  });

  it("publishes nothing until a frame, then the first tick at once", () => {
    const { d, feed, handle } = start();
    const listener = vi.fn();
    feed.subscribe(listener);
    expect(feed.getSnapshot().latest).toBeNull();
    handle.queue.push(tickerSnap([at(0)]));
    handle.status = "live";
    d.frame();
    expect(listener).toHaveBeenCalledTimes(1);
    expect(feed.getSnapshot().latest?.index).toBe("82782.37");
    expect(feed.getSnapshot().feed).toBe("live");
  });

  it("coalesces a burst into one value publish a second", () => {
    const { d, feed, handle } = start();
    const listener = vi.fn();
    feed.subscribe(listener);
    handle.status = "live";
    handle.queue.push(tickerSnap([at(0)]));
    d.frame();
    listener.mockClear();
    for (let i = 1; i <= 10; i += 1) {
      handle.queue.push(tickerDelta([at(i, 2_000_000_000_000 + i)]));
      d.frame();
    }
    expect(listener).not.toHaveBeenCalled(); // inside the second
    d.frame(PUBLISH_INTERVAL_MS);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(feed.getSnapshot().latest?.tsMs).toBe(2_000_000_000_010);
  });

  it("never replaces a newer item with an older one", () => {
    const { d, feed, handle } = start();
    handle.queue.push(tickerSnap([at(0, 2_000_000_000_500)]));
    d.frame();
    handle.queue.push(tickerDelta([at(1, 2_000_000_000_100)]));
    d.frame(PUBLISH_INTERVAL_MS);
    expect(feed.getSnapshot().latest?.tsMs).toBe(2_000_000_000_500);
  });

  it("keeps the last value across a reset", () => {
    const { d, feed, handle } = start();
    handle.queue.push(tickerSnap([at(0)]), tickerReset);
    d.frame();
    expect(feed.getSnapshot().latest?.last).toBe("82751.20");
  });

  it("accepts an older-ts snapshot after a reset, keeping the shown values meanwhile", () => {
    const { d, feed, handle } = start();
    handle.status = "live";
    handle.queue.push(tickerSnap([at(0, 1_792_391_751_229)]));
    d.frame();
    handle.queue.push(tickerReset);
    d.frame(1_000);
    expect(feed.getSnapshot().latest?.tsMs).toBe(1_792_391_751_229);
    handle.queue.push(tickerSnap([at(0, 1_792_391_746_229)]));
    d.frame(1_000);
    expect(feed.getSnapshot().latest?.tsMs).toBe(1_792_391_746_229);
  });

  it("maps a stale topic to the stale chip (t2) and keeps the values", () => {
    const { d, feed, handle } = start();
    handle.status = "live";
    handle.queue.push(tickerSnap([at(0)]));
    d.frame();
    handle.status = "stale";
    d.frame();
    expect(feed.getSnapshot().stale.tier).toBe("t2");
    expect(feed.getSnapshot().latest?.last).toBe("82751.20");
  });

  it("goes stale at 5 s (t1) and 15 s (t2) without a new item, per whole second", () => {
    const { d, feed, handle } = start();
    handle.status = "live";
    handle.queue.push(tickerSnap([at(0)]));
    d.frame();
    d.frame(5_000);
    expect(feed.getSnapshot().stale.tier).toBe("t1");
    d.frame(10_000);
    expect(feed.getSnapshot().stale.tier).toBe("t2");
    expect(feed.getSnapshot().stale.lastTsMs).toBe(at(0).ts_ms);
    handle.queue.push(tickerDelta([at(1, 2_000_000_000_000)]));
    d.frame();
    expect(feed.getSnapshot().stale.tier).toBe("fresh");
  });

  it("treats a served stale flag as t2", () => {
    expect(staleTier(0, true)).toBe("t2");
    expect(staleTier(4_999, false)).toBe("fresh");
    expect(staleTier(5_000, false)).toBe("t1");
    expect(staleTier(15_000, false)).toBe("t2");
  });

  it("stops: releases the handle, cancels the frame, is idempotent", () => {
    const { d, feed, handle } = start();
    feed.stop();
    feed.stop();
    expect(handle.release).toHaveBeenCalledTimes(1);
    expect(d.pending()).toBe(0);
  });
});
