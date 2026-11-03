// E24-S05 (#780) PR 4: AN-4 — the wording at the 2/3 split, the leading edge, the 5 s throttle, and the burst the
// ticket names: 500 prints/s for 10 s through the real feed gives at most 2 summaries, never one per print.
import { describe, expect, it } from "vitest";
import {
  CascadeSummary,
  summaryText,
} from "../../../../src/features/derivatives/liquidations/cascade";
import { startLiquidationFeed } from "../../../../src/features/derivatives/liquidations/liquidationFeed";
import { fakeClient, fakeDisplay } from "../../tape/fakeFeed";
import { delta, EXAMPLE } from "./liqFrames";

describe("summaryText (D04 AN-4, F-1 PROPOSED)", () => {
  it.each([
    [1, "mostly longs liquidated"],
    [2 / 3, "mostly longs liquidated"],
    [0.6, "on both sides"],
    [1 / 3, "mostly shorts liquidated"],
    [0, "mostly shorts liquidated"],
    [null, "on both sides"],
  ])("long share %s reads %s", (share, words) => {
    expect(summaryText(1_240, share)).toBe(`Liquidations: 1,240 per second, ${words}.`);
  });
});

describe("CascadeSummary", () => {
  it("says nothing below the threshold, then the leading edge, then at most once per 5 s", () => {
    const s = new CascadeSummary();
    expect(s.observe(9, 1, 0)).toBeNull();
    expect(s.observe(10, 1, 100)).toBe("Liquidations: 10 per second, mostly longs liquidated.");
    expect(s.observe(800, 1, 5_099)).toBeNull();
    expect(s.observe(800, 0.5, 5_100)).toBe("Liquidations: 800 per second, on both sides.");
  });

  it("says at most 2 summaries at 500 prints/s for 10 s through the feed, each naming the rate", () => {
    const fake = fakeClient();
    const d = fakeDisplay(16);
    let now = 0;
    const feed = startLiquidationFeed(fake.client, {
      symbol: "BTCUSDT",
      paneId: "liq",
      window: { fromMs: 0, toMs: 1 },
      loadHistory: () => new Promise(() => undefined),
      clock: { ...d.clock, wallNow: () => 0 },
    });
    const handle = fake.handles[0];
    if (handle === undefined) throw new Error("no handle");
    handle.status = "live";
    const summary = new CascadeSummary();
    const said: string[] = [];
    for (let push = 0; push < 20; push += 1) {
      const t0 = EXAMPLE.ts_ms + push * 500;
      handle.queue.push(
        delta(Array.from({ length: 250 }, (_, k) => ({ ...EXAMPLE, ts_ms: t0 + 2 * k }))),
      );
      for (let f = 0; f < 31; f += 1) {
        d.frame();
        now += 16;
        const s = feed.getSnapshot();
        const text = summary.observe(s.ratePerSec, s.longShare, now);
        if (text !== null) said.push(text);
      }
    }
    expect(said.length).toBeGreaterThanOrEqual(1);
    expect(said.length).toBeLessThanOrEqual(2);
    for (const text of said)
      expect(text).toBe("Liquidations: 500 per second, mostly longs liquidated.");
    feed.stop();
  });
});
