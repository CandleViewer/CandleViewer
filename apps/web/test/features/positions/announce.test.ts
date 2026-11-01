/**
 * E29-S01 (#911) the Positions tab's announcements: the serial queue over the shell's one announcer
 * (one message per region at a time, each after the region's 5 s budget, bounded), the batch order
 * (most severe first, E29-D05 §8.3), the crossing sentences (RT-05 assertive, RT-12 polite), the
 * account episodes (RT-07, RT-11: once each, synced only for an account still listed, the
 * kill-switch lock shown and not said) and RT-16's value lines.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearAnnouncements,
  lastWrittenAt,
  REGION_BUDGET_MS,
} from "../../../src/features/app-shell/announcer";
import type { AccountSignal } from "../../../src/features/positions/accountSignals";
import {
  accountAnnouncements,
  createPanelAnnouncer,
  crossingAnnouncements,
  crossingText,
  MAX_QUEUED,
  rowName,
  rowValuesText,
  sayAll,
  signOf,
  totalsValuesText,
  type Announcement,
} from "../../../src/features/positions/announce";
import type { LiqReading } from "../../../src/features/positions/model/liqTier";
import type { PositionRowModel } from "../../../src/features/positions/model/rowMapping";
import { SUB1, SUB2 } from "./support/fakes";

const ROW = {
  symbol: "ETHUSDT",
  sideWord: "Short",
  accountLabel: "Sub-1",
  accountId: SUB1,
  unrealisedPnl: "-121.5",
  r: { value: "-0.8526", source: "server" },
} as const satisfies Partial<PositionRowModel>;
const NEAR: LiqReading = {
  tier: "near",
  basis: "buffer",
  distancePct: "1.2",
  sharePct: "27",
  mmRatePct: null,
  mmRateStale: null,
  mmRateStaleSinceMs: null,
};

beforeEach(() => {
  vi.useFakeTimers();
  clearAnnouncements();
});
afterEach(() => {
  vi.useRealTimers();
  clearAnnouncements();
});

describe("the serial queue over the shell's announcer", () => {
  it("writes at once when the region's budget allows, then one message per budget, in order", () => {
    const write = vi.fn();
    let last = -Infinity;
    const announcer = createPanelAnnouncer({
      write: (politeness, text) => {
        last = Date.now();
        write(politeness, text);
      },
      lastWrittenAt: () => last,
    });
    announcer.say("polite", "one");
    announcer.say("polite", "two");
    expect(write.mock.calls).toEqual([["polite", "one"]]);
    vi.advanceTimersByTime(REGION_BUDGET_MS - 1);
    expect(write).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(write.mock.calls).toEqual([
      ["polite", "one"],
      ["polite", "two"],
    ]);
  });

  it("waits out another writer's message in the region (E17-D02 §11), and each region apart", () => {
    const write = vi.fn();
    const announcer = createPanelAnnouncer({
      write,
      lastWrittenAt: (politeness) => (politeness === "polite" ? Date.now() : -Infinity),
    });
    announcer.say("polite", "later");
    announcer.say("assertive", "now");
    expect(write.mock.calls).toEqual([["assertive", "now"]]);
  });

  it("holds at most MAX_QUEUED per region, dropping the oldest; blank text is never queued", () => {
    const write = vi.fn();
    let last = -Infinity;
    const announcer = createPanelAnnouncer({
      write: (politeness, text) => {
        last = Date.now();
        write(politeness, text);
      },
      lastWrittenAt: () => last,
    });
    announcer.say("polite", "first");
    announcer.say("polite", "  ");
    for (let i = 0; i < MAX_QUEUED + 2; i += 1) announcer.say("polite", `m${i}`);
    vi.advanceTimersByTime(REGION_BUDGET_MS * (MAX_QUEUED + 3));
    const said = write.mock.calls.map(([, text]) => text as string);
    expect(said).toHaveLength(1 + MAX_QUEUED);
    expect(said.slice(0, 2)).toEqual(["first", "m2"]);
  });

  it("says nothing after dispose, and drops what waits", () => {
    const write = vi.fn();
    let last = -Infinity;
    const announcer = createPanelAnnouncer({
      write: (p, t) => {
        last = Date.now();
        write(p, t);
      },
      lastWrittenAt: () => last,
    });
    announcer.say("polite", "one");
    announcer.say("polite", "two");
    announcer.dispose();
    vi.advanceTimersByTime(REGION_BUDGET_MS * 2);
    announcer.say("assertive", "three");
    expect(write.mock.calls).toEqual([["polite", "one"]]);
  });

  it("by default writes to the shell announcer, which records the region's write time", () => {
    const announcer = createPanelAnnouncer();
    announcer.say("assertive", "said");
    expect(lastWrittenAt("assertive")).toBe(Date.now());
  });
});

describe("sayAll: most severe first (D05 §8.3)", () => {
  it("orders by rank, equal ranks in their order", () => {
    const said: string[] = [];
    const batch: Announcement[] = [
      { politeness: "polite", text: "near", rank: 2 },
      { politeness: "assertive", text: "critical", rank: 1 },
      { politeness: "assertive", text: "lock", rank: 0 },
      { politeness: "polite", text: "reconciling", rank: 2 },
    ];
    sayAll({ say: (_p, text) => said.push(text), dispose: () => undefined }, batch);
    expect(said).toEqual(["lock", "critical", "near", "reconciling"]);
  });
});

describe("crossings (RT-05, RT-12)", () => {
  it("names the row (N-01) and the tier sentence (D02 §5.3)", () => {
    expect(rowName(ROW)).toBe("ETHUSDT Short on Sub-1");
    expect(rowName({ ...ROW, accountLabel: null })).toBe(`ETHUSDT Short on ${SUB1}`);
    expect(crossingText(ROW, NEAR)).toBe(
      "ETHUSDT Short on Sub-1: Near liquidation: 27 % of the entry buffer left, 1.2 % from liquidation",
    );
    expect(crossingText(ROW, { ...NEAR, tier: "none" })).toBeUndefined();
  });

  it("Near is polite and Critical assertive; a row or a reading gone says nothing", () => {
    const rows = new Map([["k", ROW as unknown as PositionRowModel]]);
    const out = crossingAnnouncements(
      [
        { key: "k", crossing: "near" },
        { key: "k", crossing: "critical" },
        { key: "gone", crossing: "critical" },
      ],
      (key) => rows.get(key),
      (key) => (key === "k" ? NEAR : undefined),
    );
    expect(out.map((a) => [a.politeness, a.rank])).toEqual([
      ["polite", 2],
      ["assertive", 1],
    ]);
  });
});

const signal = (
  state: "reconciling" | "desync" | "stale",
  episode: number,
  killLock = false,
): AccountSignal => ({ oms: { state, sinceMs: 0, episode, killLock } });

describe("the account episodes (RT-07, RT-11)", () => {
  const label = (id: string): string => (id === SUB1 ? "Sub-1" : "Sub-2");
  const listed = (): boolean => true;

  it("says each new episode once, in D03 §4.1's words and region", () => {
    const first = accountAnnouncements(
      new Map(),
      new Map([
        [SUB1, signal("reconciling", 1)],
        [SUB2, signal("stale", 2)],
      ]),
      "owner",
      label,
      listed,
    );
    expect(first.batch).toEqual([
      {
        politeness: "polite",
        text: "Reconciling Sub-1 with Bybit. Closing, cancelling and tightening stops still work.",
        rank: 2,
      },
      {
        politeness: "assertive",
        text: "Sub-2 is locked for new orders: reconciliation with Bybit failed for 2 minutes. Closing, cancelling and tightening stops still work.",
        rank: 0,
      },
    ]);
    const again = accountAnnouncements(
      first.said,
      new Map([
        [SUB1, signal("reconciling", 1)],
        [SUB2, signal("stale", 2)],
      ]),
      "owner",
      label,
      listed,
    );
    expect(again.batch).toEqual([]);
  });

  it("an episode's end is synced for a listed account, nothing for one withdrawn", () => {
    const said = new Map([
      [SUB1, 1],
      [SUB2, 2],
    ]);
    const out = accountAnnouncements(said, new Map(), "viewer", label, (id) => id === SUB1);
    expect(out.batch).toEqual([
      { politeness: "polite", text: "Sub-1 reconciled with Bybit.", rank: 2 },
    ]);
    expect(out.said.size).toBe(0);
  });

  it("the kill-switch lock is shown, not said (no deck announcement)", () => {
    const out = accountAnnouncements(
      new Map(),
      new Map([[SUB2, signal("stale", 3, true)]]),
      "manager",
      label,
      listed,
    );
    expect(out.batch).toEqual([]);
    expect(out.said.get(SUB2)).toBe(3);
  });
});

describe("RT-16's lines", () => {
  it("reads the sign of a decimal, and the row's and the totals' values as CMP-116 does", () => {
    expect([signOf("-0.1"), signOf("0"), signOf("2.5"), signOf(null), signOf("x")]).toEqual([
      -1,
      0,
      1,
      null,
      null,
    ]);
    expect(rowValuesText(ROW, "USDT")).toBe(
      "ETHUSDT Short on Sub-1: uPnL loss 121.5 USDT, R loss 0.85 R",
    );
    expect(rowValuesText({ ...ROW, r: { value: null, reason: "no_stop" } }, "USDT")).toBe(
      "ETHUSDT Short on Sub-1: uPnL loss 121.5 USDT, R unavailable: no stop price",
    );
    expect(rowValuesText({ ...ROW, r: { value: null, reason: "no_price" } }, "USDT")).toBe(
      "ETHUSDT Short on Sub-1: uPnL loss 121.5 USDT, R unavailable",
    );
    expect(totalsValuesText("LIVE total", "-205.84", "USDT")).toBe(
      "LIVE total: uPnL loss 205.84 USDT",
    );
  });
});
