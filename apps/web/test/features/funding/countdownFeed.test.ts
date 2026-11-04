// E24-S03 (#778) slice 2: the countdown entry: ticker, charge marks, settlement once, staleness, registry.
import { describe, expect, it, vi } from "vitest";
import type { FundingCharge, SecondTick } from "@candleviewer/ui";
import {
  acquireCountdownFeed,
  startCountdownFeed,
} from "../../../src/features/funding/countdownFeed";
import { fakeClient, fakeDisplay } from "../tape/fakeFeed";
import { recordedFundingItems, snap } from "./support/tickerFrames";

const ITEM = recordedFundingItems()[0];
const NEXT = 1792396800000; // the recorded `nextFundingTime`

function manualTick(startMs: number) {
  let nowMs = startMs;
  const listeners = new Set<() => void>();
  const tick: SecondTick = {
    now: () => nowMs,
    subscribe: (l) => {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
  };
  return {
    tick,
    listeners,
    at: (ms: number) => {
      nowMs = ms;
      for (const l of [...listeners]) l();
    },
  };
}

const flush = async (): Promise<void> => {
  await Promise.resolve();
  await Promise.resolve();
};

const PAY = { accountLabel: "Demo 1", env: "DEMO", direction: "pay", amountUsdt: "12.40" } as const;

function setup(startMs = NEXT - 600_000) {
  const fake = fakeClient();
  const display = fakeDisplay(100);
  const t = manualTick(startMs);
  const loadCharges = vi.fn(async () => [PAY] as readonly FundingCharge[]);
  const feed = startCountdownFeed(fake.client, {
    symbol: "BTCUSDT",
    tick: t.tick,
    loadCharges,
    clock: display.clock,
  });
  const handle = fake.handles[0];
  if (handle === undefined) throw new Error("no handle");
  handle.status = "live";
  const push = (over: Partial<typeof ITEM> = {}) => {
    handle.queue.push(snap([{ ...ITEM, ...over } as NonNullable<typeof ITEM>]));
    display.frame();
  };
  const settled = vi.fn();
  feed.onSettlement(settled);
  return { fake, display, t, loadCharges, feed, handle, push, settled };
}

describe("funding countdown entry", () => {
  it("subscribes the symbol's ticker once and publishes its rate and next time", () => {
    const { fake, feed, push } = setup();
    expect(fake.specs[0]).toMatchObject({ ch: "ticker.BTCUSDT", paneId: "funding:BTCUSDT" });
    push();
    expect(feed.getSnapshot()).toMatchObject({
      feed: "live",
      rate: ITEM?.funding_rate,
      nextFundingTimeMs: NEXT,
      charges: [],
    });
  });

  it("reads the charges at the 5 minute mark and at 1 minute, never in between or before", async () => {
    const { t, loadCharges, feed, push } = setup();
    push();
    t.at(NEXT - 301_000);
    expect(loadCharges).not.toHaveBeenCalled();
    t.at(NEXT - 300_000);
    await flush();
    expect(loadCharges).toHaveBeenCalledOnce();
    expect(feed.getSnapshot().charges).toEqual([PAY]);
    t.at(NEXT - 120_000);
    t.at(NEXT - 60_000);
    t.at(NEXT - 30_000);
    expect(loadCharges).toHaveBeenCalledTimes(2);
  });

  it("reads once at mount inside the window, never shows a charge after a failed read", async () => {
    const { t, loadCharges, feed, push } = setup(NEXT - 200_000);
    loadCharges.mockRejectedValueOnce(new Error("x"));
    push();
    await flush();
    expect(loadCharges).toHaveBeenCalledOnce();
    expect(feed.getSnapshot().charges).toEqual([]);
    t.at(NEXT - 60_000);
    await flush();
    expect(feed.getSnapshot().charges).toEqual([PAY]);
  });

  it("signals the settlement once per deadline, clears the lines, and restarts on the advanced time", async () => {
    const { t, feed, push, loadCharges, settled } = setup(NEXT - 100_000);
    push();
    await flush();
    expect(feed.getSnapshot().charges).toEqual([PAY]);
    t.at(NEXT);
    t.at(NEXT + 1_000);
    expect(settled).toHaveBeenCalledExactlyOnceWith(NEXT);
    expect(feed.getSnapshot().charges).toEqual([]);
    const advanced = NEXT + 8 * 3_600_000;
    push({ next_funding_time_ms: advanced });
    expect(feed.getSnapshot().nextFundingTimeMs).toBe(advanced);
    t.at(advanced - 300_000);
    expect(loadCharges).toHaveBeenCalledTimes(2);
    t.at(advanced);
    expect(settled).toHaveBeenLastCalledWith(advanced);
  });

  it("signals a deadline the tick never reached when the ticker advances past it, once (M1)", () => {
    const { t, push, settled } = setup(NEXT - 600_000);
    push();
    const advanced = NEXT + 8 * 3_600_000;
    push({ next_funding_time_ms: advanced }); // the frame lands before any tick passed NEXT
    expect(settled).toHaveBeenCalledExactlyOnceWith(NEXT);
    t.at(NEXT + 1_000);
    push({ next_funding_time_ms: advanced });
    expect(settled).toHaveBeenCalledOnce();
    t.at(advanced);
    expect(settled).toHaveBeenLastCalledWith(advanced);
    expect(settled).toHaveBeenCalledTimes(2);
  });

  it("goes stale at 5 s and 15 s without an update, and at once on the server's flag", () => {
    const { display, feed, push } = setup();
    push();
    for (let i = 0; i < 50; i += 1) display.frame();
    expect(feed.getSnapshot().stale).toMatchObject({ tier: "t1", ageS: 5 });
    for (let i = 0; i < 100; i += 1) display.frame();
    expect(feed.getSnapshot().stale.tier).toBe("t2");
    push({ stale: true });
    expect(feed.getSnapshot().stale.tier).toBe("t2");
    push();
    expect(feed.getSnapshot().stale.tier).toBe("fresh");
  });

  it("is one entry per symbol for every holder, stopped by the last release", () => {
    const fake = fakeClient();
    const display = fakeDisplay();
    const t = manualTick(0);
    const options = { symbol: "BTCUSDT", tick: t.tick, loadCharges: vi.fn(), clock: display.clock };
    const header = acquireCountdownFeed(fake.client, options);
    const pane = acquireCountdownFeed(fake.client, options);
    expect(pane.feed).toBe(header.feed);
    expect(fake.client.consume).toHaveBeenCalledOnce();
    expect(t.listeners.size).toBe(1);
    header.release();
    header.release();
    expect(fake.handles[0]?.release).not.toHaveBeenCalled();
    pane.release();
    expect(fake.handles[0]?.release).toHaveBeenCalledOnce();
    expect(t.listeners.size).toBe(0);
    expect(display.pending()).toBe(0);
    const again = acquireCountdownFeed(fake.client, options);
    expect(again.feed).not.toBe(header.feed);
    again.release();
  });
});
