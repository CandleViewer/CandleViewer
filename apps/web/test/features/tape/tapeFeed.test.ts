// E22-S01 (#714) PR-A: the feed loop, structured through the existing TopicHandle (BQ-207, BQ-208).
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  browserClock,
  startTapeFeed,
  TAPE_SYMBOL,
} from "../../../src/features/tape/model/tapeFeed";
import { delta, item, items, reset, snap } from "./frames";
import { fakeClient, fakeDisplay } from "./fakeFeed";

const start = (symbol = "BTCUSDT") => {
  const fake = fakeClient();
  const display = fakeDisplay();
  const feed = startTapeFeed(fake.client, { symbol, paneId: "tape-1", clock: display.clock });
  const handle = fake.handles[0];
  if (handle === undefined) throw new Error("no handle");
  return { ...fake, display, feed, handle };
};

describe("tape feed", () => {
  it("consumes trades.{symbol} structured with no other option (BQ-207)", () => {
    const { specs } = start();
    expect(specs).toEqual([
      {
        ch: "trades.BTCUSDT",
        opts: { encoding: "structured" },
        paneId: "tape-1",
        priority: "other",
      },
    ]);
  });

  it("refuses a symbol that is not a USDT perpetual, before subscribing", () => {
    const fake = fakeClient();
    for (const symbol of ["btcusdt", "BTCUSD", "BTC-USDT", "trades.X", ""]) {
      expect(TAPE_SYMBOL.test(symbol)).toBe(false);
      expect(() => startTapeFeed(fake.client, { symbol, paneId: "p" })).toThrow(RangeError);
    }
    expect(fake.client.consume).not.toHaveBeenCalled();
  });

  it("applies nothing on arrival, and everything that arrived at the next animation frame", () => {
    const { display, feed, handle } = start();
    const onFrame = vi.fn();
    feed.onFrame(onFrame);
    handle.queue.push(snap(items(1, 3)), delta([item(4)]));
    expect(feed.ring.length).toBe(0);
    display.frame();
    expect(feed.ring.length).toBe(4);
    expect(onFrame).toHaveBeenCalledWith(4);
    expect(display.pending()).toBe(1); // the loop keeps reading while it runs
    display.frame();
    expect(onFrame).toHaveBeenLastCalledWith(0);
  });

  it("follows the handle's status into the store at once", () => {
    const { display, feed, handle } = start();
    expect(feed.store.getSnapshot().feed).toBe("pending");
    handle.status = "live";
    display.frame();
    expect(feed.store.getSnapshot().feed).toBe("live");
    handle.status = "resyncing";
    handle.queue.push(reset("gap"));
    display.frame();
    expect(feed.store.getSnapshot().feed).toBe("resyncing");
  });

  it("publishes the rows, rate and threshold to the store", () => {
    const { display, feed, handle } = start();
    handle.queue.push(snap(items(1, 10), { big_trade_threshold: "500000" }));
    display.frame();
    expect(feed.store.getSnapshot()).toMatchObject({
      rows: 10,
      ratePerSec: 10,
      threshold: "500000",
      lastPrintTsMs: item(10).ts_ms,
    });
  });

  it("keeps in-memory metrics: ingest counters, ticks and ingest time (BQ-209)", () => {
    const { display, feed, handle } = start();
    handle.queue.push(delta([item(1)], { dropped: 2, coalesced: true, coalesced_count: 3 }));
    display.frame();
    display.frame();
    expect(feed.metrics()).toMatchObject({
      ticks: 2,
      received: 1,
      appended: 1,
      serverDropped: 2,
      coalescedFrames: 1,
      coalescedCount: 3,
      lastIngestMs: 0,
      maxIngestMs: 0,
    });
  });

  it("tells the client the pane's visibility, until stopped", () => {
    const { client, feed } = start();
    feed.setVisibility("offscreen");
    expect(client.setPane).toHaveBeenCalledWith("tape-1", "offscreen");
    feed.stop();
    feed.setVisibility("visible");
    expect(client.setPane).toHaveBeenCalledTimes(1);
  });

  it("releases the subscription and stops the loop once, back to idle", () => {
    const { display, feed, handle } = start();
    const onFrame = vi.fn();
    const off = feed.onFrame(onFrame);
    feed.stop();
    feed.stop();
    expect(handle.release).toHaveBeenCalledTimes(1);
    expect(display.pending()).toBe(0);
    expect(feed.store.getSnapshot().feed).toBe("idle");
    display.frame();
    expect(onFrame).not.toHaveBeenCalled();
    off();
  });

  it("an unsubscribed frame listener is not called", () => {
    const { display, feed } = start();
    const onFrame = vi.fn();
    feed.onFrame(onFrame)();
    display.frame();
    expect(onFrame).not.toHaveBeenCalled();
  });

  it("runs on the display's animation frames by default", () => {
    const raf = vi.fn(() => 7);
    const caf = vi.fn();
    vi.stubGlobal("requestAnimationFrame", raf);
    vi.stubGlobal("cancelAnimationFrame", caf);
    const feed = startTapeFeed(fakeClient().client, { symbol: "BTCUSDT", paneId: "p" });
    expect(raf).toHaveBeenCalledTimes(1);
    feed.stop();
    expect(caf).toHaveBeenCalledWith(7);
    expect(typeof browserClock().now()).toBe("number");
  });
});

afterEach(() => vi.unstubAllGlobals());
