/** E08-S08 (#4702): the client's share of the `ticker` rebuild budget (E08-D07 D6, §4.6; 23 §7.5, §8.5). */
import { describe, expect, it } from "vitest";
import {
  BACKOFF_FIRST_MS,
  BACKOFF_MAX_MS,
  CHANGE_SPACING_MS,
  CLIENT_DRAWS,
  REBUILD_WINDOW_MS,
  createBackoff,
  createRebuildShare,
} from "../../../src/features/watchlist/ticker/rebuildShare";

describe("rebuild share", () => {
  it("leaves one of the topic's 5 draws a minute for a resync: the client starts at most 4", () => {
    expect([CLIENT_DRAWS, REBUILD_WINDOW_MS, CHANGE_SPACING_MS]).toEqual([4, 60_000, 2_000]);
  });

  it("a fresh connection may start at once", () => {
    expect(createRebuildShare().nextStart(1_000)).toBe(1_000);
  });

  it("changes go at least 2 s apart", () => {
    const share = createRebuildShare();
    share.record(10_000);
    expect(share.nextStart(10_500)).toBe(12_000);
    expect(share.nextStart(12_500)).toBe(12_500);
  });

  it("with 4 draws in the last 60 s the next starts when the oldest of them leaves the window", () => {
    const share = createRebuildShare();
    for (const at of [0, 3_000, 6_000, 9_000]) share.record(at);
    expect(share.drawsIn(9_000)).toBe(4);
    expect(share.nextStart(9_500)).toBe(60_000);
    expect(share.drawsIn(60_000)).toBe(3); // the draw at 0 no longer counts
    share.record(60_000);
    expect(share.nextStart(61_000)).toBe(63_000); // the draw at 3 000 leaves next
  });

  it("counts only the last 60 s", () => {
    const share = createRebuildShare();
    share.record(0);
    share.record(30_000);
    expect(share.drawsIn(59_999)).toBe(2);
    expect(share.drawsIn(60_000)).toBe(1);
    expect(share.drawsIn(90_000)).toBe(0);
  });
});

describe("resync_rate_limited back-off (23 §8.5)", () => {
  it("waits 5 s, then twice as long after each further refusal, up to 60 s", () => {
    const backoff = createBackoff();
    const waits = Array.from({ length: 7 }, () => backoff.next());
    expect(waits).toEqual([5_000, 10_000, 20_000, 40_000, 60_000, 60_000, 60_000]);
    expect([BACKOFF_FIRST_MS, BACKOFF_MAX_MS]).toEqual([5_000, 60_000]);
  });

  it("a subscription that lands resets it", () => {
    const backoff = createBackoff();
    backoff.next();
    backoff.next();
    backoff.reset();
    expect(backoff.next()).toBe(5_000);
  });
});
