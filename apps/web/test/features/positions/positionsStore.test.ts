/**
 * E29-S01 (#911) the positions store: `23` §15's late-frame rule (older dropped, equal replaces),
 * `removed` after the upserts, BQ-18's sources (REST first paint and fallback, a `snap` replacing
 * it wholesale), resets (the last good view until the next `snap`), and the reset and revocation
 * cache drop with E29-D05 F-02's line (OM-I04, SR-E29-11). Frames are the shipped mappers' goldens.
 */
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DeltaFrame } from "../../../src/lib/ws/api";
import type { generated } from "@candleviewer/protocol";
import {
  accountInfo,
  type AccountInfo,
  type ExchangeAccount,
  type RestPosition,
} from "../../../src/features/positions/model/rowMapping";
import {
  createPositionsStore,
  MAX_TOMBSTONES,
  usePositions,
  type PositionsStore,
} from "../../../src/features/positions/positionsStore";
import { delta, golden, MAIN, reset, snap, SUB1, SUB2 } from "./support/fakes";

type Positions = generated.ws.Positions;
type Item = Positions["positions"][number];
const snapshot = golden<Positions>("ws_positions_snapshot.json");
const deltas = golden<{ case: string; body: Positions }[]>("ws_positions_deltas.json");
const bodyOf = (name: string): Positions => deltas.find((d) => d.case === name)?.body as Positions;
const restItems = golden<{ items: RestPosition[] }>("rest_list_positions.json").items;
const wallet = golden<generated.ws.Wallet>("ws_wallet_snapshot.json");
const directory = golden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json")
  .items.map(accountInfo)
  .filter((a): a is AccountInfo => a !== null);
const item = (symbol: string, account: string): Item =>
  snapshot.positions.find((p) => p.symbol === symbol && p.exchange_account_id === account) as Item;
/** The snapshot under a narrowing that took SUB2 (`23` §9.5's `reconfigure` snap). */
const kept = snapshot.positions.filter((p) => p.exchange_account_id !== SUB2);

function started(): PositionsStore {
  const store = createPositionsStore();
  store.setStarted(true);
  store.setAccounts(directory);
  store.commit();
  return store;
}
const live = (): PositionsStore => {
  const store = started();
  store.applyFrames([snap(snapshot)]);
  store.commit();
  return store;
};
const markOf = (
  store: PositionsStore,
  symbol: string,
  account: string,
): string | null | undefined =>
  store.getSnapshot().rows.find((r) => r.symbol === symbol && r.accountId === account)?.mark;

describe("the late-frame rule (23 §15)", () => {
  it("drops a delta older than the held item", () => {
    const store = live();
    store.applyFrames([delta(bodyOf("late"))]);
    store.commit();
    expect(markOf(store, "ETHUSDT", SUB1)).toBe("2561");
  });

  it("applies a newer one, and an equal one replaces", () => {
    const store = live();
    store.applyFrames([delta(bodyOf("update"))]);
    store.commit();
    expect(markOf(store, "BTCUSDT", MAIN)).toBe("64112");
    const held = bodyOf("update").positions[0] as Item;
    store.applyFrames([delta({ positions: [{ ...held, mark_price: "64200" }] })]);
    store.commit();
    expect(markOf(store, "BTCUSDT", MAIN)).toBe("64200");
  });

  it("drops an item without updated_at_ms or a key", () => {
    const store = live();
    const unstamped = Object.fromEntries(
      Object.entries(item("SOLUSDT", SUB2)).filter(([key]) => key !== "updated_at_ms"),
    );
    store.applyFrames([
      delta({ positions: [{ ...unstamped, mark_price: "1" }, { symbol: "BTCUSDT" }, 7] }),
    ]);
    store.commit();
    expect(markOf(store, "SOLUSDT", SUB2)).toBe("147.8");
    expect(store.getSnapshot().rows).toHaveLength(5);
  });
});

describe("removed, after the upserts (23 §15.2)", () => {
  it("a flat position's frame removes its row", () => {
    const store = live();
    store.applyFrames([delta(bodyOf("flat"))]);
    store.commit();
    expect(store.getSnapshot().rows.map((r) => `${r.accountId}|${r.symbol}`)).not.toContain(
      `${SUB2}|BTCUSDT`,
    );
    expect(store.getSnapshot().rows).toHaveLength(4);
  });

  it("an upsert and the removal of the same position in one frame: removed", () => {
    const store = live();
    const sol = item("SOLUSDT", SUB2);
    store.applyFrames([
      delta({
        positions: [{ ...sol, updated_at_ms: sol.updated_at_ms + 5, mark_price: "150" }],
        removed: [sol.id],
      }),
    ]);
    store.commit();
    expect(markOf(store, "SOLUSDT", SUB2)).toBeUndefined();
  });

  it("an item that reads flat is a removal too", () => {
    const store = live();
    const sol = item("SOLUSDT", SUB2);
    store.applyFrames([
      delta({ positions: [{ ...sol, side: "flat", updated_at_ms: sol.updated_at_ms + 5 }] }),
    ]);
    store.commit();
    expect(markOf(store, "SOLUSDT", SUB2)).toBeUndefined();
  });
});

describe("a REST read never brings back what was taken (SR-E29-11)", () => {
  it("one that lands after a revocation is ignored; a withdrawn account stays out while its line stands", () => {
    const store = live();
    store.applyFrames([reset("revoked")]);
    store.applyRest(restItems, 9_000);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "revoked", source: "none", rows: [] });
    store.markRetrying();
    store.dismissWithdrawn(MAIN);
    store.applyRest(restItems, 9_100);
    store.commit();
    expect(store.getSnapshot().rows.map((r) => r.accountId)).toEqual([MAIN]);
  });

  it("one that lands during a narrowing brings none of its accounts, nor a withdrawn one's", () => {
    const store = live();
    store.applyFrames([reset("narrowed")]);
    store.applyRest(restItems, 9_000);
    store.commit();
    expect(store.getSnapshot().rows).toEqual([]);
    store.setAccounts(directory.filter((a) => a.id !== SUB2));
    store.applyRest(restItems, 9_100);
    store.commit();
    expect(store.getSnapshot().rows.map((r) => r.accountId)).toEqual([MAIN, SUB1, SUB1]);
    expect(store.getSnapshot().source).toBe("rest");
  });

  it("a fallback read after the narrowed snap brings the kept accounts back, not the candidate", () => {
    const store = live();
    // `23` §9.5: the reset, then the snap built under the new scope: it serves MAIN and SUB1 only
    store.applyFrames([reset("narrowed"), snap({ positions: kept })]);
    // the link drops before the directory has settled the narrowing; REST is the fallback
    store.setLink(false);
    store.applyFrames([reset("reconnect")]);
    store.applyRest(restItems, 9_000);
    store.commit();
    expect(store.getSnapshot().source).toBe("rest");
    // the snap released the accounts it served; SUB2 is still a candidate, so its rows stay out
    expect(store.getSnapshot().rows.map((r) => r.accountId)).toEqual([MAIN, SUB1, SUB1]);
  });

  it("an over-cap account's rows leave when the cap is known, and no read brings them back", () => {
    const store = started();
    store.applyRest(restItems, 1_000);
    store.setOverCap([SUB2]);
    store.commit();
    expect(store.getSnapshot().rows.map((r) => r.accountId)).toEqual([MAIN, SUB1, SUB1]);
    store.applyRest(restItems, 2_000);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ withdrawn: [], overCap: [SUB2] });
    expect(store.getSnapshot().rows).toHaveLength(3);
  });
});

describe("a removed row stays removed for the baseline's life (23 §6.2.3, §15)", () => {
  const btc = (): Item => item("BTCUSDT", SUB2);

  it("a late item stamped at or before the removal is dropped; a later one reopens it", () => {
    const store = live();
    store.applyFrames([delta(bodyOf("flat"))]); // SUB2 BTCUSDT, by id
    store.applyFrames([
      delta({ positions: [{ ...btc(), updated_at_ms: btc().updated_at_ms - 1 }] }),
    ]);
    store.applyFrames([delta({ positions: [btc()] })]); // the very row that was removed
    store.commit();
    expect(store.getSnapshot().rows).toHaveLength(4);
    store.applyFrames([
      delta({ positions: [{ ...btc(), updated_at_ms: btc().updated_at_ms + 1 }] }),
    ]);
    store.commit();
    expect(store.getSnapshot().rows).toHaveLength(5);
  });

  it("a flat item's own stamp bounds it; the next snapshot starts afresh", () => {
    const store = live();
    const at = btc().updated_at_ms + 50;
    store.applyFrames([delta({ positions: [{ ...btc(), side: "flat", updated_at_ms: at }] })]);
    store.applyFrames([delta({ positions: [{ ...btc(), updated_at_ms: at - 10 }] })]);
    store.commit();
    expect(store.getSnapshot().rows).toHaveLength(4);
    store.applyFrames([snap(snapshot)]);
    store.commit();
    expect(store.getSnapshot().rows).toHaveLength(5); // a snapshot says what is open
  });

  it("remembers at most MAX_TOMBSTONES removals, the oldest forgotten first", () => {
    const store = live();
    const symbols = Array.from({ length: MAX_TOMBSTONES + 1 }, (_, i) => `S${i}USDT`);
    const flat = (symbol: string): Item => ({ ...btc(), symbol, side: "flat" });
    store.applyFrames([delta({ positions: symbols.map(flat) })]);
    const late = (n: number): Item => ({
      ...btc(),
      symbol: `S${n}USDT`,
      id: `0d000000-0000-4000-8000-${String(900 + n).padStart(12, "0")}`,
    });
    store.applyFrames([delta({ positions: [late(0), late(1)] })]);
    store.commit();
    const shown = store.getSnapshot().rows.map((r) => r.symbol);
    expect(shown).toContain("S0USDT"); // forgotten: its late item is taken
    expect(shown).not.toContain("S1USDT");
  });
});

describe("sources (BQ-18)", () => {
  it("REST is first paint while the snapshot is pending; a snap replaces it wholesale", () => {
    const store = started();
    store.applyRest(restItems.slice(0, 2), 1_000);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "loading", source: "rest", asOfMs: 1_000 });
    expect(store.getSnapshot().rows.map((r) => r.size)).toEqual(["0.250", "0.100"]);
    store.applyFrames([snap(snapshot, 2_000)]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "live", source: "ws", asOfMs: 2_000 });
    expect(store.getSnapshot().rows).toHaveLength(5);
  });

  it("a REST read after the snapshot is ignored", () => {
    const store = live();
    store.applyRest([], 9_000);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ source: "ws" });
    expect(store.getSnapshot().rows).toHaveLength(5);
  });

  it("a delta before any snapshot extends nothing", () => {
    const store = started();
    store.applyFrames([delta(bodyOf("update"))]);
    store.commit();
    expect(store.getSnapshot().rows).toEqual([]);
  });

  it("the link down reads offline; the fallback read replaces the last good view", () => {
    const store = live();
    store.setLink(false);
    store.applyFrames([reset("reconnect")]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "offline", source: "last_good" });
    expect(store.getSnapshot().rows).toHaveLength(5);
    store.applyRest(restItems.slice(0, 1), 5_000);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ source: "rest", asOfMs: 5_000 });
    store.setLink(true);
    store.applyFrames([snap(snapshot)]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "live", source: "ws" });
  });
});

describe("resets", () => {
  it.each(["gap", "malformed", "overflow", "resnapshot"] as const)(
    "%s keeps the last good rows until the next snap",
    (reason) => {
      const store = live();
      store.applyFrames([reset(reason), delta(bodyOf("update"))]);
      store.commit();
      expect(store.getSnapshot()).toMatchObject({ status: "resyncing", source: "last_good" });
      expect(markOf(store, "BTCUSDT", MAIN)).toBe("64012"); // no delta extends a void baseline
      store.applyFrames([snap({ positions: [item("BTCUSDT", MAIN)] })]);
      store.commit();
      expect(store.getSnapshot()).toMatchObject({ status: "live", source: "ws" });
      expect(store.getSnapshot().rows).toHaveLength(1);
    },
  );

  it("narrowed: every row leaves at once; the directory names who left (F-02)", () => {
    const store = live();
    store.applyFrames([reset("narrowed")]);
    store.commit();
    expect(store.getSnapshot().rows).toEqual([]);
    expect(store.takeNarrowed()).toBe(true);
    expect(store.takeNarrowed()).toBe(false);
    store.setEffective({ exchange_account_ids: [MAIN, SUB1, SUB2] }); // the old list: no news
    store.applyFrames([snap({ positions: kept })]);
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([]);
    store.setAccounts(directory.filter((a) => a.id !== SUB2));
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([{ accountId: SUB2, label: "Sub-2" }]);
    expect(store.getSnapshot().rows.map((r) => r.accountId)).toEqual([MAIN, SUB1, SUB1]);
  });

  it("narrowed: a narrowed sub_ok (a fresh subscription) names who left before the directory", () => {
    const store = live();
    store.applyFrames([reset("narrowed")]);
    store.setEffective({ exchange_account_ids: [MAIN, SUB1] });
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([{ accountId: SUB2, label: "Sub-2" }]);
    store.setAccounts(directory.filter((a) => a.id !== SUB2)); // named once
    store.commit();
    expect(store.getSnapshot().withdrawn).toHaveLength(1);
  });

  it("narrowed: a directory that lists every account names no one (an account_disabled gap)", () => {
    const store = live();
    store.applyFrames([reset("narrowed"), snap({ positions: kept })]);
    store.setAccounts(directory);
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([]);
    store.setAccounts(directory.filter((a) => a.id !== SUB2)); // later: SUB2 had no rows by then
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([]);
  });

  it("narrowed, then revoked: every account the narrowing took is named", () => {
    const store = live();
    store.applyFrames([reset("narrowed"), snap({ positions: kept }), reset("revoked")]);
    store.commit();
    expect(store.getSnapshot().withdrawn.map((w) => w.label)).toEqual(["Main", "Sub-1", "Sub-2"]);
    expect(store.takeNarrowed()).toBe(false); // ended: nothing to re-read
  });

  it("revoked after data: the subscription ends, every account's rows leave with its line", () => {
    const store = live();
    store.applyFrames([reset("revoked")]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "revoked", rows: [] });
    expect(store.getSnapshot().withdrawn.map((w) => w.label)).toEqual(["Main", "Sub-1", "Sub-2"]);
    store.dismissWithdrawn(MAIN);
    store.dismissWithdrawn(MAIN);
    store.commit();
    expect(store.getSnapshot().withdrawn.map((w) => w.label)).toEqual(["Sub-1", "Sub-2"]);
  });

  it("revoked before any snapshot is a refusal: Could not load, no line", () => {
    const store = started();
    store.applyRest(restItems, 1);
    store.applyFrames([reset("revoked")]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({
      status: "snapshot_failed",
      rows: [],
      withdrawn: [],
    });
  });

  it("an over-cap account is never named withdrawn, though no sub_ok names it", () => {
    const store = live();
    store.applyFrames([reset("narrowed")]);
    store.setOverCap([SUB2]);
    store.setEffective({ exchange_account_ids: [MAIN, SUB1] });
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([]);
  });

  it("a narrowed sub_ok drops the account it no longer names", () => {
    const store = live();
    store.setEffective({ exchange_account_ids: [MAIN, SUB2] });
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([{ accountId: SUB1, label: "Sub-1" }]);
    expect(store.getSnapshot().rows.map((r) => r.accountId)).toEqual([MAIN, SUB2, SUB2]);
    store.setEffective({ exchange_account_ids: ["not-a-uuid"] }); // ignored: not a sub_ok's list
    store.commit();
    expect(store.getSnapshot().rows).toHaveLength(3);
  });

  it("an account the directory no longer lists leaves with its line", () => {
    const store = live();
    store.setAccounts(directory.filter((a) => a.id !== MAIN));
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([{ accountId: MAIN, label: "Main" }]);
    expect(store.getSnapshot().rows).toHaveLength(4);
  });
});

describe("states", () => {
  it("no accounts, and a directory that could not be read", () => {
    const store = createPositionsStore();
    store.setStarted(true);
    store.setAccounts([]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "no_accounts", accountsLoaded: true });
    const failed = createPositionsStore();
    failed.setStarted(true);
    failed.setAccounts(null);
    failed.commit();
    expect(failed.getSnapshot().status).toBe("snapshot_failed");
  });

  it("S-02: a missed budget fails until a retry or a snap; a held snapshot never fails", () => {
    const store = started();
    store.markSnapshotFailed();
    store.commit();
    expect(store.getSnapshot().status).toBe("snapshot_failed");
    store.markRetrying();
    store.commit();
    expect(store.getSnapshot().status).toBe("loading");
    store.markSnapshotFailed();
    store.applyFrames([snap(snapshot)]);
    store.commit();
    expect(store.getSnapshot().status).toBe("live");
    store.markSnapshotFailed();
    store.commit();
    expect(store.getSnapshot().status).toBe("live");
  });

  it("Empty state: a live snapshot with no positions", () => {
    const store = started();
    store.applyFrames([snap({ positions: [] })]);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "live", rows: [] });
  });

  it("stopping drops every cache", () => {
    const store = live();
    store.setOverCap([SUB2]);
    store.setStarted(false);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({
      status: "idle",
      rows: [],
      accounts: [],
      overCap: [],
    });
  });
});

describe("wallet: the MM rate, today's realised PnL", () => {
  it("a cross account's rows take their tier from the MM rate (BQ-11)", () => {
    const store = live();
    store.applyWallet([snap(wallet)]);
    store.commit();
    const sub2btc = store
      .getSnapshot()
      .rows.find((r) => r.accountId === SUB2 && r.symbol === "BTCUSDT");
    expect(store.getSnapshot().liq.get(sub2btc?.key ?? "")).toMatchObject({
      tier: "near",
      basis: "mm_rate",
      mmRatePct: "72",
    });
  });

  it("the MM rate's balance staleness reaches the reading (23 §15.4)", () => {
    const store = live();
    const sub2 = wallet.balances[2] as generated.ws.Wallet["balances"][number];
    const keyOf = (): string =>
      store.getSnapshot().rows.find((r) => r.accountId === SUB2 && r.symbol === "BTCUSDT")?.key ??
      "";
    store.applyWallet([snap({ balances: [{ ...sub2, stale: true, stale_since_ms: 1_000 }] })]);
    store.commit();
    expect(store.getSnapshot().liq.get(keyOf())).toMatchObject({
      basis: "mm_rate",
      mmRateStale: true,
      mmRateStaleSinceMs: 1_000,
    });
    store.applyWallet([
      delta({
        balances: [{ ...sub2, stale_since_ms: null, updated_at_ms: sub2.updated_at_ms + 1 }],
      }),
    ]);
    store.commit();
    expect(store.getSnapshot().liq.get(keyOf())).toMatchObject({
      mmRateStale: false,
      mmRateStaleSinceMs: null,
    });
    const isolated = store.getSnapshot().rows.find((r) => r.accountId === SUB1)?.key ?? "";
    expect(store.getSnapshot().liq.get(isolated)).toMatchObject({ mmRateStale: null });
  });

  it("before any wallet frame, the REST balance's rate has no known staleness", () => {
    const store = createPositionsStore();
    store.setStarted(true);
    store.setAccounts(directory.map((a) => (a.id === SUB2 ? { ...a, mmRate: "0.72" } : a)));
    store.applyFrames([snap(snapshot)]);
    store.commit();
    const key = store.getSnapshot().rows.find((r) => r.accountId === SUB2)?.key ?? "";
    expect(store.getSnapshot().liq.get(key)).toMatchObject({
      basis: "mm_rate",
      mmRatePct: "72",
      mmRateStale: null,
    });
  });

  it("realised_pnl_today, when served, per account; an older item is dropped", () => {
    const store = live();
    const balance = wallet.balances[0] as generated.ws.Wallet["balances"][number];
    store.applyWallet([snap({ balances: [{ ...balance, realised_pnl_today: "37.40" }] })]);
    store.applyWallet([
      delta({
        balances: [
          { ...balance, realised_pnl_today: "1", updated_at_ms: balance.updated_at_ms - 1 },
        ],
      }),
    ]);
    store.commit();
    expect(store.getSnapshot().realisedToday.get(MAIN)).toBe("37.40");
    store.applyWallet([reset("revoked")]);
    store.commit();
    expect(store.getSnapshot().realisedToday.size).toBe(0);
  });
});

describe("commits (the 10 Hz tick)", () => {
  it("inputs notify no one until a commit; a commit with nothing new publishes nothing", () => {
    const store = started();
    const listener = vi.fn();
    store.subscribe(listener);
    store.applyFrames([snap(snapshot)]);
    store.applyFrames([delta(bodyOf("update"))]);
    expect(listener).not.toHaveBeenCalled();
    const version = store.getSnapshot().version;
    expect(store.commit()).toBe(true);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().version).toBe(version + 1);
    expect(store.commit()).toBe(false);
  });

  it("a crossing is told in the commit that finds it, once", () => {
    const store = live();
    const eth = item("ETHUSDT", SUB1);
    store.applyFrames([
      delta({ positions: [{ ...eth, mark_price: "2580", updated_at_ms: eth.updated_at_ms + 9 }] }),
    ]);
    store.commit();
    expect(store.getSnapshot().crossings).toEqual([
      expect.objectContaining({ crossing: "critical", key: `${SUB1}|ETHUSDT|0` }),
    ]);
    store.applyFrames([
      delta({ positions: [{ ...eth, mark_price: "2581", updated_at_ms: eth.updated_at_ms + 10 }] }),
    ]);
    store.commit();
    expect(store.getSnapshot().crossings).toEqual([]);
  });

  it("ignores frames it cannot read: binary bodies, payloads without positions", () => {
    const store = live();
    store.applyFrames([
      { ...(delta({}) as DeltaFrame), body: { e: "b64", bytes: new ArrayBuffer(4) } },
      delta({ positions: "x" }),
      delta(null),
    ]);
    store.applyWallet([delta({ balances: [{ exchange_account_id: "x" }, null] }), delta({})]);
    store.commit();
    expect(store.getSnapshot().rows).toHaveLength(5);
  });

  it("over-cap accounts are named once", () => {
    const store = live();
    store.setOverCap([SUB2]);
    store.commit();
    expect(store.commit()).toBe(false);
    store.setOverCap([SUB2]);
    expect(store.commit()).toBe(false);
    expect(store.getSnapshot().overCap).toEqual([SUB2]);
  });
});

describe("teardown (every subscription lets go)", () => {
  it("a listener that unsubscribed hears no later commit", () => {
    const store = started();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.applyFrames([snap(snapshot)]);
    store.commit();
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    unsubscribe(); // twice is harmless
    store.applyFrames([delta(bodyOf("update"))]);
    expect(store.commit()).toBe(true);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("usePositions unsubscribes on unmount", () => {
    const store = live();
    const released = vi.fn();
    const watched: PositionsStore = {
      ...store,
      subscribe: (listener) => {
        const off = store.subscribe(listener);
        return () => {
          released();
          off();
        };
      },
    };
    const { result, unmount } = renderHook(() => usePositions(watched, (s) => s.rows.length));
    expect(result.current).toBe(5);
    unmount();
    expect(released).toHaveBeenCalledTimes(1);
  });
});
