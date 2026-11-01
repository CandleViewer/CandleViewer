/**
 * E29-S02 (#912) the store: the keyed map, `23` §15's late-frame rule, `removed` after the linger,
 * the focused row kept, BQ-6's REST side map (first paint, held and untracked kept, the creation
 * constants), a revoked account's rows dropped at once, the resets, and the scenarios' store half:
 * "Cancel that lost the race" (BQ-3) and BQ-1's three `change: "amend"` steps, from the goldens.
 */
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TopicFrame } from "../../../../src/lib/ws/api";
import {
  createOrdersStore,
  LINGER_MS,
  MAX_TOMBSTONES,
  useOrders,
  type OrdersStore,
} from "../../../../src/features/positions/orders/ordersStore";
import { stateLabel, type WsOrder } from "../../../../src/features/positions/orders/model/orderRow";
import {
  ADOPTED,
  COND,
  delta,
  deltaBody,
  directory,
  ENTRY,
  ETH,
  HELD,
  MAIN,
  NEW,
  reset,
  restOpen,
  snap,
  snapshotBody,
  STOP,
  SUB1,
  SUB2,
  TP,
  UNTRACKED,
  wsItem,
  type DeltaCase,
} from "./support/orders";

/** The monotonic clock the linger runs on, and the wall clock of a REST read. */
const NOW = 1_000_000;
const WALL = Date.UTC(2026, 9, 31, 14, 2, 11);
/** A frame's `ts`: just after the snapshot read (READ_AT). */
const TS = WALL + 100;

const accounts = () => [...directory().values()];
function fail(): never {
  throw new Error("row missing");
}
const d = (name: DeltaCase, ts = TS + 1_000): TopicFrame => delta(deltaBody(name), ts);

/** Started, the directory known, REST's first paint, then the snapshot: the live view. */
function live(store: OrdersStore = createOrdersStore()): OrdersStore {
  store.setStarted(true);
  store.setAccounts(accounts());
  store.applyRest(restOpen(), WALL);
  store.applyFrames([snap(snapshotBody(), TS)], NOW);
  store.commit();
  return store;
}
const rowsOf = (store: OrdersStore) => store.getSnapshot().rows;
const idsOf = (store: OrdersStore) => rowsOf(store).map((r) => r.id);
const rowOf = (store: OrdersStore, id: string) => rowsOf(store).find((r) => r.id === id);
const apply = (store: OrdersStore, frames: TopicFrame[], now = NOW): void => {
  store.applyFrames(frames, now);
  store.commit();
};

describe("first paint and the snapshot (BQ-6)", () => {
  it("REST is first paint while the topic is pending: every open order, held and untracked too", () => {
    const store = createOrdersStore();
    store.setStarted(true);
    store.applyRest(restOpen(), WALL);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "loading", source: "rest", asOfMs: WALL });
    expect(idsOf(store)).toHaveLength(7);
  });

  it("the snapshot is authoritative; REST's held and untracked stay, as WS never sends them", () => {
    const store = live();
    expect(store.getSnapshot()).toMatchObject({ status: "live", source: "ws", asOfMs: TS });
    // env → account → created, oldest first (D01 D13 a)
    expect(idsOf(store)).toEqual([TP, HELD, UNTRACKED, COND, ENTRY, STOP, ETH]);
    expect(rowOf(store, HELD)).toMatchObject({
      source: "rest",
      state: { word: "Held — owner review" },
    });
    expect(rowOf(store, TP)?.source).toBe("ws");
  });

  it("REST's other rows yield to the snapshot: one it does not list is not shown", () => {
    const store = createOrdersStore();
    store.setStarted(true);
    store.applyRest(restOpen(), WALL);
    const only = snapshotBody();
    store.applyFrames([snap({ orders: only.orders.filter((o) => o.id !== ETH) }, TS)], NOW);
    store.commit();
    expect(idsOf(store)).not.toContain(ETH);
    expect(idsOf(store)).toContain(HELD);
  });

  it("REST's creation constants give Age and provenance; they never override WS state or terms", () => {
    const store = live();
    expect(rowOf(store, STOP)).toMatchObject({ provenance: "recorded_stop", source: "ws" });
    expect(rowOf(store, TP)?.createdAtMs).toBe(WALL - (72 * 60 + 0) * 1000);
    apply(store, [d("amend_request")]);
    store.applyRest(restOpen(), WALL + 5_000); // REST still says submitted, at 2500.00
    store.commit();
    expect(rowOf(store, ETH)).toMatchObject({
      source: "ws",
      price: "2500",
      state: { word: "Amending" },
    });
  });

  it("each read replaces the last whole: a held order a newer read no longer lists leaves", () => {
    const store = live();
    store.applyRest(
      restOpen().filter((o) => o.id !== HELD),
      WALL + 1,
    );
    store.commit();
    expect(idsOf(store)).not.toContain(HELD);
    expect(idsOf(store)).toContain(UNTRACKED);
  });
});

describe("the keyed map: O(1) per item", () => {
  it("a delta replaces its order alone; every other row keeps its object", () => {
    const store = live();
    const before = new Map(rowsOf(store).map((r) => [r.id, r]));
    apply(store, [d("amend_request")]);
    for (const row of rowsOf(store)) {
      if (row.id === ETH) expect(row).not.toBe(before.get(ETH));
      else expect(row).toBe(before.get(row.id));
    }
  });

  it("many frames in one drain commit once; nothing new commits nothing", () => {
    const store = live();
    const listener = vi.fn();
    store.subscribe(listener);
    store.applyFrames([d("amend_request"), d("amend_accepted", TS + 2_000)], NOW);
    expect(listener).not.toHaveBeenCalled();
    expect(store.commit()).toBe(true);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.commit()).toBe(false);
  });

  it("a malformed item (no id, no stamp, no account) and a binary body are dropped", () => {
    const store = live();
    const item = wsItem(snapshotBody(), TP);
    const stampless: Record<string, unknown> = { ...item };
    delete stampless["updated_at_ms"];
    const binary = d("amend_request") as Extract<TopicFrame, { kind: "d" }>;
    apply(store, [
      delta({
        orders: [{ ...item, id: "nope" }, stampless, { ...item, exchange_account_id: "x" }],
      }),
      { ...binary, body: { e: "b64", bytes: new ArrayBuffer(4) } },
    ]);
    expect(rowOf(store, TP)?.updatedAtMs).toBe(item.updated_at_ms);
    expect(rowOf(store, ETH)?.state.word).toBe("Working");
  });
});

describe("23 §15: the late-frame rule", () => {
  it("an item older than the held one is dropped; an equal one replaces it", () => {
    const store = live();
    expect(rowOf(store, ENTRY)?.filledQty).toBe("0.05");
    apply(store, [d("late")]); // stamped before the snapshot read
    expect(rowOf(store, ENTRY)?.filledQty).toBe("0.05");
    const held = wsItem(snapshotBody(), ENTRY);
    apply(store, [delta({ orders: [{ ...held, filled_qty: "0.07" }] })]);
    expect(rowOf(store, ENTRY)?.filledQty).toBe("0.07");
  });

  it("a removed order stays removed: an item stamped at or before its removal is late", () => {
    const store = live();
    apply(store, [d("cancel_request", TS + 3_000), d("cancel_lost_race", TS + 4_000)]);
    store.expire(NOW + LINGER_MS);
    store.commit();
    expect(idsOf(store)).not.toContain(TP);
    apply(store, [d("cancel_request", TS + 5_000)]); // the cancel frame, re-sent late
    expect(idsOf(store)).not.toContain(TP);
  });

  it("a removal outlives a resnapshot: the snapshot's older item never brings the order back", () => {
    const store = live();
    apply(store, [d("cancel_request", TS + 3_000), d("cancel_lost_race", TS + 4_000)]);
    store.expire(NOW + LINGER_MS);
    store.commit();
    expect(idsOf(store)).not.toContain(TP);
    // the snapshot's TP is stamped before its fill: late against the tomb kept across baselines
    apply(store, [reset("resnapshot"), snap(snapshotBody(), TS + 9_000)], NOW + LINGER_MS);
    expect(store.getSnapshot().status).toBe("live");
    expect(idsOf(store)).not.toContain(TP);
  });

  it("a second removal stamped earlier keeps the later tomb, so an item between them stays out", () => {
    const store = live();
    apply(store, [delta({ orders: [], removed: [HELD] }, TS + 9_000)]);
    apply(store, [delta({ orders: [], removed: [HELD] }, TS + 5_000)]);
    const between = { ...wsItem(snapshotBody(), TP), id: HELD, updated_at_ms: TS + 6_000 };
    apply(store, [delta({ orders: [between] }, TS + 9_500)]);
    expect(idsOf(store)).not.toContain(HELD);
  });

  it("the store remembers at most MAX_TOMBSTONES removals, the oldest forgotten first", () => {
    const store = live();
    const base = wsItem(snapshotBody(), TP);
    const id = (n: number) => `0f000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
    const ended = (n: number): WsOrder => ({
      ...base,
      id: id(n),
      lifecycle_state: "cancelled",
      state: "cancelled",
      updated_at_ms: base.updated_at_ms + 10,
    });
    const all = Array.from({ length: MAX_TOMBSTONES + 1 }, (_, n) => ended(n));
    apply(store, [delta({ orders: all })]);
    store.expire(NOW + LINGER_MS);
    apply(store, [
      delta({ orders: [{ ...ended(0), lifecycle_state: "submitted", state: "accepted" }] }),
    ]);
    apply(store, [
      delta({ orders: [{ ...ended(1), lifecycle_state: "submitted", state: "accepted" }] }),
    ]);
    expect(idsOf(store)).toContain(id(0)); // forgotten: a late frame of it gets in again
    expect(idsOf(store)).not.toContain(id(1));
  });
});

describe("Cancel that lost the race (BQ-3): no error, no 'already filled'", () => {
  it("the order filled before the cancel arrived: Cancelling, then Filled, lingering 5 s, then gone", () => {
    const store = live();
    apply(store, [d("cancel_request", TS + 3_000)]);
    expect(stateLabel(rowOf(store, TP) ?? fail())).toBe("Cancelling");
    apply(store, [d("cancel_lost_race", TS + 4_000)], NOW + 10);
    expect(rowOf(store, TP)?.state).toMatchObject({ word: "Filled", terminal: true });
    expect(store.getSnapshot().lingering.get(TP)).toBe(NOW + 10 + LINGER_MS);
    store.expire(NOW + 10 + LINGER_MS - 1);
    store.commit();
    expect(idsOf(store)).toContain(TP);
    store.expire(NOW + 10 + LINGER_MS);
    store.commit();
    expect(idsOf(store)).not.toContain(TP);
  });

  it("the venue's 110001: Unknown — checking until reconciliation finds it filled", () => {
    const store = live();
    apply(store, [d("cancel_request", TS + 3_000), d("cancel_110001", TS + 4_000)]);
    expect(rowOf(store, TP)?.state).toMatchObject({
      word: "Unknown — checking",
      family: "checking",
    });
    expect(rowOf(store, TP)?.change).toBeNull();
    store.expire(NOW + 60_000);
    store.commit();
    expect(idsOf(store)).toContain(TP); // not removed: `unknown` is open
    apply(store, [d("reconcile_filled", TS + 6_000)], NOW + 60_000);
    expect(rowOf(store, TP)).toMatchObject({ change: "reconcile", state: { word: "Filled" } });
    store.expire(NOW + 60_000 + LINGER_MS);
    store.commit();
    expect(idsOf(store)).not.toContain(TP);
  });
});

describe("the focused row is kept (D01 D13 d, 05 §3.4.3)", () => {
  it("a focused order that ended never leaves while it has focus; it goes once focus moves", () => {
    const store = live();
    store.setFocused(TP.toUpperCase());
    apply(store, [d("cancel_lost_race", TS + 4_000)]);
    store.expire(NOW + LINGER_MS * 3);
    store.commit();
    expect(idsOf(store)).toContain(TP);
    expect(store.getSnapshot().focusedId).toBe(TP);
    store.setFocused(ETH);
    store.expire(NOW + LINGER_MS * 3);
    store.commit();
    expect(idsOf(store)).not.toContain(TP);
  });

  it("a focused open order a new snapshot does not list lingers instead of vanishing", () => {
    const store = live();
    store.setFocused(ETH);
    const without = snapshotBody().orders.filter((o) => o.id !== ETH);
    apply(store, [reset("resnapshot"), snap({ orders: without }, TS + 9_000)], NOW);
    expect(idsOf(store)).toContain(ETH);
    store.setFocused(null);
    store.expire(NOW + LINGER_MS);
    store.commit();
    expect(idsOf(store)).not.toContain(ETH);
  });

  it("an ended row keeps lingering through a resnapshot that no longer lists it (D01 D13 d)", () => {
    const store = live();
    apply(store, [d("cancel_lost_race", TS + 4_000)]);
    const without = snapshotBody().orders.filter((o) => o.id !== TP);
    apply(store, [reset("resnapshot"), snap({ orders: without }, TS + 9_000)], NOW + 1_000);
    expect(rowOf(store, TP)?.state.word).toBe("Filled");
    expect(store.getSnapshot().lingering.has(TP)).toBe(true);
    store.expire(NOW + LINGER_MS);
    store.commit();
    expect(idsOf(store)).not.toContain(TP);
  });
});

describe("BQ-1: every amend step says amend; the state and the terms tell them apart", () => {
  it("the request is Amending on the old terms; the acceptance is Working on the new ones", () => {
    const store = live();
    apply(store, [d("amend_request", TS + 1_000)]);
    expect(rowOf(store, ETH)).toMatchObject({
      change: "amend",
      price: "2500",
      state: { word: "Amending" },
    });
    apply(store, [d("amend_accepted", TS + 2_000)]);
    expect(rowOf(store, ETH)).toMatchObject({
      change: "amend",
      price: "2495",
      state: { word: "Working" },
    });
  });

  it("a rejection is Working on the old terms; a fault is Unknown — checking with no change", () => {
    const store = live();
    apply(store, [d("amend_request", TS + 1_000), d("amend_rejected", TS + 2_000)]);
    expect(rowOf(store, ETH)).toMatchObject({
      change: "amend",
      price: "2500",
      state: { word: "Working" },
    });
    const other = live();
    apply(other, [d("amend_request", TS + 1_000), d("amend_unknown", TS + 2_000)]);
    expect(rowOf(other, ETH)).toMatchObject({
      change: null,
      state: { word: "Unknown — checking" },
    });
  });
});

describe("held and untracked (BQ-6, S9): shown, never managed, and kept when removed", () => {
  it("an adopted untracked order arrives with `removed` and stays, never lingering", () => {
    const store = live();
    apply(store, [d("untracked_adopted", TS + 7_000)]);
    expect(rowOf(store, ADOPTED)?.state).toMatchObject({
      word: "Untracked — not placed by CandleViewer",
      family: "untracked",
    });
    expect(store.getSnapshot().lingering.has(ADOPTED)).toBe(false);
    store.expire(NOW + LINGER_MS * 2);
    store.commit();
    expect(idsOf(store)).toContain(ADOPTED);
  });

  it("an order put on hold stays as Held — owner review; a resnapshot keeps it", () => {
    const store = live();
    apply(store, [d("held", TS + 8_000)]);
    expect(rowOf(store, COND)?.state.word).toBe("Held — owner review");
    // a snapshot that lists the order as open is a new baseline: its item stands
    apply(store, [reset("resnapshot"), snap(snapshotBody(), TS + 9_000)]);
    expect(rowOf(store, COND)?.state.word).toBe("Working");
    // one that does not list it (the snapshot never holds a held order) keeps the held row
    const store2 = live();
    apply(store2, [d("held", TS + 8_000)]);
    const without = snapshotBody().orders.filter((o) => o.id !== COND);
    apply(store2, [reset("resnapshot"), snap({ orders: without }, TS + 9_000)]);
    expect(rowOf(store2, COND)?.state.word).toBe("Held — owner review");
  });

  it("a `removed` id that only REST holds supersedes REST's row", () => {
    const store = live();
    apply(store, [delta({ orders: [], removed: [HELD] }, TS + 9_000)]);
    expect(idsOf(store)).not.toContain(HELD);
  });

  /** COND put on hold over WS, then a reconnect whose snapshot (open orders only) leaves it out. */
  function carriedHeld(): OrdersStore {
    const store = live();
    apply(store, [d("held", TS + 8_000)]);
    const without = snapshotBody().orders.filter((o) => o.id !== COND);
    apply(store, [reset("reconnect"), snap({ orders: without }, TS + 9_000)]);
    expect(rowOf(store, COND)?.state.word).toBe("Held — owner review");
    return store;
  }
  const readWithout = (id: string) => restOpen().filter((o) => o.id !== id);

  it("a carried held row a complete open read no longer lists has closed: it leaves at the next frame", () => {
    const store = carriedHeld();
    store.applyRest(readWithout(COND), WALL + 10_000, NOW + 2_000);
    store.commit();
    store.expire(NOW + 2_016);
    store.commit();
    expect(idsOf(store)).not.toContain(COND);
    expect(idsOf(store)).toContain(UNTRACKED); // REST-only rows keep following the read
  });

  it("a truncated read settles nothing, and a read that lists the order keeps it", () => {
    const store = carriedHeld();
    store.applyRest(readWithout(COND), WALL + 10_000); // truncated: no settle time
    store.expire(NOW + LINGER_MS * 2);
    store.commit();
    expect(rowOf(store, COND)?.state.word).toBe("Held — owner review");
    const other = carriedHeld();
    other.applyRest(restOpen(), WALL + 10_000, NOW + 2_000);
    other.expire(NOW + LINGER_MS * 2);
    other.commit();
    expect(rowOf(other, COND)?.state.word).toBe("Held — owner review");
  });

  it("a WS frame for it after the snapshot wins over the read; a focused one leaves once focus moves", () => {
    const store = carriedHeld();
    const held = deltaBody("held").orders[0] as WsOrder;
    apply(store, [delta({ orders: [{ ...held, updated_at_ms: held.updated_at_ms + 1 }] })]);
    store.applyRest(readWithout(COND), WALL + 10_000, NOW + 2_000);
    store.expire(NOW + LINGER_MS * 2);
    store.commit();
    expect(idsOf(store)).toContain(COND);
    const focused = carriedHeld();
    focused.setFocused(COND);
    focused.applyRest(readWithout(COND), WALL + 10_000, NOW + 2_000);
    focused.expire(NOW + LINGER_MS * 2);
    focused.commit();
    expect(idsOf(focused)).toContain(COND);
    focused.setFocused(null);
    focused.expire(NOW + LINGER_MS * 2);
    focused.commit();
    expect(idsOf(focused)).not.toContain(COND);
  });
});

describe("Age's start (D02:272): REST's created_at, else the created frame's stamp", () => {
  it("a new order is hidden while validated, shows once it sends, its Age from the created frame", () => {
    const store = live();
    apply(store, [d("created", TS + 500)]);
    expect(idsOf(store)).not.toContain(NEW);
    apply(store, [d("submitted", TS + 600)]);
    const created = deltaBody("created").orders[0]?.updated_at_ms;
    expect(rowOf(store, NEW)).toMatchObject({ createdAtMs: created, state: { word: "Sending" } });
    apply(store, [d("acked", TS + 700)]);
    expect(rowOf(store, NEW)?.state.word).toBe("Working");
    // the newest Main order joins the end of Main's group
    expect(idsOf(store).indexOf(NEW)).toBe(idsOf(store).indexOf(HELD) + 1);
  });
});

describe("a revoked account's rows are dropped (SR-E29-11)", () => {
  it("revoked: every row leaves at once, lingering and focused ones too, with the F-02 lines", () => {
    const store = live();
    store.setFocused(TP);
    apply(store, [d("cancel_lost_race", TS + 4_000)]);
    apply(store, [reset("revoked")]);
    const snapshot = store.getSnapshot();
    expect(snapshot.rows).toEqual([]);
    expect(snapshot.lingering.size).toBe(0);
    expect(snapshot.focusedId).toBeNull();
    expect(snapshot.status).toBe("revoked");
    expect(snapshot.withdrawn.map((w) => w.label).sort()).toEqual(["Main", "Sub-1", "Sub-2"]);
  });

  it("no REST read brings a revoked view back until Retry", () => {
    const store = live();
    apply(store, [reset("revoked")]);
    store.applyRest(restOpen(), WALL + 1);
    store.commit();
    expect(rowsOf(store)).toEqual([]);
    store.markRetrying();
    apply(store, [snap(snapshotBody(), TS + 10_000)]);
    expect(store.getSnapshot().status).toBe("live");
  });

  it("an account the directory no longer lists leaves with its line; a read from before brings none back", () => {
    const store = live();
    store.setAccounts(accounts().filter((a) => a.id !== SUB2));
    store.applyRest(restOpen(), WALL + 1);
    store.commit();
    expect(rowsOf(store).some((r) => r.accountId === SUB2)).toBe(false);
    expect(store.getSnapshot().withdrawn).toEqual([{ accountId: SUB2, label: "Sub-2" }]);
    store.dismissWithdrawn(SUB2);
    store.commit();
    expect(store.getSnapshot().withdrawn).toEqual([]);
  });

  it("an account the subscription no longer names (a narrowed sub_ok) leaves at once", () => {
    const store = live();
    store.setEffective({ exchange_account_ids: [MAIN, SUB1] });
    store.commit();
    expect(rowsOf(store).some((r) => r.accountId === SUB2)).toBe(false);
    expect(store.getSnapshot().withdrawn.map((w) => w.accountId)).toEqual([SUB2]);
    store.setEffective({}); // no sub_ok yet: nothing
  });

  it("a narrowing drops every row, asks for the directory, and its snapshot brings the kept back", () => {
    const store = live();
    apply(store, [reset("narrowed")]);
    expect(rowsOf(store)).toEqual([]);
    expect(store.takeNarrowed()).toBe(true);
    expect(store.takeNarrowed()).toBe(false);
    store.applyRest(restOpen(), WALL + 1); // set out before: none of the candidates' rows
    store.commit();
    expect(rowsOf(store)).toEqual([]);
    const kept = snapshotBody().orders.filter((o) => o.exchange_account_id !== SUB2);
    apply(store, [snap({ orders: kept }, TS + 10_000)]);
    expect(rowsOf(store).map((r) => r.accountId)).not.toContain(SUB2);
    store.setAccounts(accounts().filter((a) => a.id !== SUB2));
    store.commit();
    expect(store.getSnapshot().withdrawn.map((w) => w.accountId)).toEqual([SUB2]);
  });

  it("over the cap: an account no subscription names leaves, with no line", () => {
    const store = live();
    store.setOverCap([SUB1]);
    store.setOverCap([SUB1]);
    store.commit();
    expect(rowsOf(store).some((r) => r.accountId === SUB1)).toBe(false);
    expect(store.getSnapshot()).toMatchObject({ withdrawn: [], overCap: [SUB1] });
  });
});

describe("resets and statuses", () => {
  it("a gap voids the baseline: the last good rows stay, no delta extends them, the next snap replaces", () => {
    const store = live();
    apply(store, [reset("gap"), d("amend_request")]);
    expect(store.getSnapshot()).toMatchObject({ status: "resyncing", source: "last_good" });
    expect(rowOf(store, ETH)?.state.word).toBe("Working");
    const without = snapshotBody().orders.filter((o) => o.id !== ETH);
    apply(store, [snap({ orders: without }, TS + 9_000)]);
    expect(store.getSnapshot().status).toBe("live");
    expect(idsOf(store)).not.toContain(ETH);
    expect(idsOf(store)).toContain(HELD);
  });

  it("idle, loading, no accounts, snapshot failed and its Retry, offline", () => {
    const store = createOrdersStore();
    store.commit();
    expect(store.getSnapshot().status).toBe("idle");
    store.setStarted(true);
    store.setStarted(true);
    store.commit();
    expect(store.getSnapshot().status).toBe("loading");
    store.setAccounts(null);
    store.commit();
    expect(store.getSnapshot().status).toBe("snapshot_failed");
    store.setAccounts(accounts());
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "loading", accountsLoaded: true });
    store.markSnapshotFailed();
    store.markSnapshotFailed();
    store.commit();
    expect(store.getSnapshot().status).toBe("snapshot_failed");
    store.markRetrying();
    store.setLink(false);
    store.setLink(false);
    store.commit();
    expect(store.getSnapshot().status).toBe("offline");
    store.setLink(true);
    store.setAccounts([]);
    store.commit();
    expect(store.getSnapshot().status).toBe("no_accounts");
  });

  it("revoked before any snapshot is a failed load (S-02)", () => {
    const store = createOrdersStore();
    store.setStarted(true);
    apply(store, [reset("revoked")]);
    expect(store.getSnapshot().status).toBe("snapshot_failed");
  });

  it("stopping drops every cache", () => {
    const store = live();
    store.setStarted(false);
    store.commit();
    expect(store.getSnapshot()).toMatchObject({ status: "idle", rows: [], accountsLoaded: false });
    store.setStarted(true);
    store.applyFrames([d("amend_request")], NOW);
    store.commit();
    expect(rowsOf(store)).toEqual([]); // no baseline: a delta extends nothing
  });

  it("useOrders unsubscribes on unmount", () => {
    const store = live();
    const released = vi.fn();
    const watched: OrdersStore = {
      ...store,
      subscribe: (listener) => {
        const off = store.subscribe(listener);
        return () => {
          released();
          off();
        };
      },
    };
    const { result, unmount } = renderHook(() => useOrders(watched, (s) => s.rows.length));
    expect(result.current).toBe(7);
    unmount();
    expect(released).toHaveBeenCalledTimes(1);
  });

  it("an order for the stop on Sub-2 is a native stop through REST's provenance", () => {
    expect(rowOf(live(), STOP)?.protective).toEqual({ kind: "native_stop", via: "provenance" });
  });

  it("Sub-1's untracked order keeps its REST row while WS never sends it", () => {
    const store = live();
    expect(rowOf(store, UNTRACKED)).toMatchObject({ accountId: SUB1, source: "rest" });
  });
});
