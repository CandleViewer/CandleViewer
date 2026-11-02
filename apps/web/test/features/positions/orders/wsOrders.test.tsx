/**
 * E29-S02 (#912) the feed, on fake timers: the `orders` subscription (private, no `open_only`,
 * BQ-14), the drain every animation frame (no 10 Hz tick), the `state.apply` / `paint` marks with
 * `ws_frame_apply_seconds{topic=orders}`, REST at first paint and after each snapshot (BQ-6, never on
 * a timer, the newest read alone applied), S-02's 5 s budget and Retry, a narrowing named through
 * the directory, the subscription's teardown on unmount, and no exchange text in the DOM (BQ-2).
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountsOutcome, ExchangeAccount } from "../../../../src/features/positions/api";
import type { OrdersApi, OrdersOutcome } from "../../../../src/features/positions/orders/api";
import {
  priceLabel,
  stateLabel,
  triggerLabel,
  type RestOrder,
} from "../../../../src/features/positions/orders/model/orderRow";
import {
  createOrdersStore,
  LINGER_MS,
  useOrders,
  type OrdersStore,
} from "../../../../src/features/positions/orders/ordersStore";
import {
  APPLY_MEASURE,
  MARK_PREFIX,
  MAX_MEASURES,
  ORDERS_PANE_ID,
  SNAPSHOT_BUDGET_MS,
  startOrdersFeed,
  useOrdersFeed,
  type OrdersFeed,
} from "../../../../src/features/positions/orders/wsOrders";
import {
  COND,
  delta,
  deltaBody,
  ETH,
  exchangeAccounts,
  fakeClient,
  fakeRaf,
  HELD,
  MAIN,
  reset,
  restOpen,
  snap,
  snapshotBody,
  SUB1,
  SUB2,
  TP,
  type DeltaCase,
  type FakeClient,
} from "./support/orders";

const FRAME = 16;

function fakeApi(over: Partial<OrdersApi> = {}): OrdersApi & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    listOrders: vi.fn(async (): Promise<OrdersOutcome> => {
      calls.push("orders");
      return { kind: "ok", items: restOpen(), truncated: false };
    }),
    listExchangeAccounts: vi.fn(async (): Promise<AccountsOutcome> => {
      calls.push("accounts");
      return { kind: "ok", items: exchangeAccounts() };
    }),
    ...over,
  };
}

let ws: FakeClient;
let store: OrdersStore;
let feed: OrdersFeed | undefined;
const perf = { mark: vi.fn(), measure: vi.fn(), clearMarks: vi.fn(), clearMeasures: vi.fn() };

function start(
  api: OrdersApi = fakeApi(),
  extra: Partial<Parameters<typeof startOrdersFeed>[0]> = {},
): OrdersFeed {
  feed = startOrdersFeed({
    client: ws.client,
    store,
    api,
    ...fakeRaf,
    now: () => Date.now(),
    performance: perf,
    ...extra,
  });
  return feed;
}
const settle = async (ms = 0): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};
const ordersHandle = () => ws.live("orders")[0];
const d = (name: DeltaCase) => delta(deltaBody(name));

beforeEach(() => {
  vi.useFakeTimers();
  ws = fakeClient();
  store = createOrdersStore();
  for (const fn of Object.values(perf)) fn.mockReset();
});
afterEach(() => {
  feed?.stop();
  feed = undefined;
  vi.useRealTimers();
});

describe("the orders subscription", () => {
  it("consumes orders for the directory's accounts, private, in SCR-063's pane, without open_only", async () => {
    start();
    await settle();
    expect(ordersHandle()?.spec).toEqual({
      ch: "orders",
      opts: { exchange_account_ids: [MAIN, SUB1, SUB2] },
      paneId: ORDERS_PANE_ID,
      priority: "private",
    });
    expect(ordersHandle()?.spec.opts).not.toHaveProperty("open_only");
  });

  it("names at most 25 accounts; REST names the same 25 once the directory is known", async () => {
    const first = exchangeAccounts()[0] as ExchangeAccount;
    const many: ExchangeAccount[] = Array.from({ length: 27 }, (_, i) => ({
      ...first,
      id: `a2000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
      label: `Acct ${i}`,
    }));
    const api = fakeApi({
      listExchangeAccounts: vi.fn(async (): Promise<AccountsOutcome> => ({
        kind: "ok",
        items: many,
      })),
    });
    start(api);
    await settle();
    const named = (ordersHandle()?.spec.opts as { exchange_account_ids: string[] })
      .exchange_account_ids;
    expect(named).toHaveLength(25);
    expect(store.getSnapshot().overCap).toHaveLength(0); // committed at the next frame
    await settle(FRAME);
    expect(store.getSnapshot().overCap).toEqual(many.slice(25).map((a) => a.id));
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(FRAME);
    const last = vi.mocked(api.listOrders).mock.calls.at(-1)?.[0];
    expect(last).toEqual({ accountIds: named, openOnly: true });
  });

  it("no accounts: nothing to subscribe to", async () => {
    start(fakeApi({ listExchangeAccounts: async () => ({ kind: "ok", items: [] }) }));
    await settle(FRAME);
    expect(ws.handles).toEqual([]);
    expect(store.getSnapshot().status).toBe("no_accounts");
  });
});

describe("drained every animation frame (BQ-14: no 10 Hz tick)", () => {
  it("REST is first paint; frames wait for the next animation frame and commit once in it", async () => {
    start();
    await settle(FRAME);
    expect(store.getSnapshot()).toMatchObject({ status: "loading", source: "rest" });
    const listener = vi.fn();
    store.subscribe(listener);
    ordersHandle()?.push(snap(snapshotBody()), d("amend_request"), d("amend_accepted"));
    expect(listener).not.toHaveBeenCalled(); // never applied on arrival (C9)
    await settle(FRAME);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot()).toMatchObject({ status: "live", source: "ws" });
    listener.mockClear();
    await settle(FRAME * 10);
    expect(listener).toHaveBeenCalledTimes(1); // the REST read the snapshot asked for, once
    await settle(FRAME * 10);
    expect(listener).toHaveBeenCalledTimes(1); // nothing new: no commit
  });

  it("the loop keeps running: an arrival is applied at the next frame, within 16 ms", async () => {
    start();
    await settle(FRAME);
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(FRAME);
    ordersHandle()?.push(d("amend_request")); // right after a frame drained the handle
    await settle(FRAME - 1);
    expect(store.getSnapshot().rows.find((r) => r.id === ETH)?.state.word).toBe("Working");
    await settle(1);
    expect(store.getSnapshot().rows.find((r) => r.id === ETH)?.state.word).toBe("Amending");
  });

  it("each frame ends the lingers due: a filled order leaves after its 5 s", async () => {
    start();
    await settle(FRAME);
    ordersHandle()?.push(snap(snapshotBody()), d("cancel_lost_race"));
    await settle(FRAME);
    expect(store.getSnapshot().rows.some((r) => r.id === TP)).toBe(true);
    await settle(LINGER_MS - FRAME);
    expect(store.getSnapshot().rows.some((r) => r.id === TP)).toBe(true);
    await settle(FRAME * 2); // the first frame at or past the linger's end
    expect(store.getSnapshot().rows.some((r) => r.id === TP)).toBe(false);
  });

  it("marks state.apply and paint, and measures ws_frame_apply_seconds{topic=orders} for a frame that applied frames", async () => {
    start();
    await settle(FRAME * 3);
    expect(perf.mark).not.toHaveBeenCalled(); // idle frames write nothing
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(FRAME);
    expect(perf.mark.mock.calls.map(([name]) => name)).toEqual([
      `${MARK_PREFIX}state.apply`,
      `${MARK_PREFIX}paint`,
    ]);
    expect(perf.measure).toHaveBeenCalledTimes(1);
    expect(perf.measure.mock.calls[0]).toEqual([
      APPLY_MEASURE,
      { start: expect.any(Number), end: expect.any(Number), detail: { topic: "orders" } },
    ]);
    expect(APPLY_MEASURE).toBe("ws_frame_apply_seconds");
    expect(perf.clearMarks).toHaveBeenCalledWith(`${MARK_PREFIX}paint`);
  });

  it("keeps a bounded number of measures (MAX_MEASURES by default); a throwing measure never stops the feed", async () => {
    expect(MAX_MEASURES).toBe(1_000);
    start(fakeApi(), { maxMeasures: 3 });
    await settle(FRAME);
    for (let i = 0; i < 7; i += 1) {
      ordersHandle()?.push(d("amend_request"));
      await settle(FRAME);
    }
    expect(perf.measure).toHaveBeenCalledTimes(7);
    expect(perf.clearMeasures).toHaveBeenCalledTimes(2);
    feed?.stop();
    ws = fakeClient();
    store = createOrdersStore();
    start(fakeApi(), {
      performance: {
        mark: () => undefined,
        measure: () => {
          throw new Error("x");
        },
      },
    });
    await settle(FRAME);
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(FRAME);
    expect(store.getSnapshot().status).toBe("live");
  });

  it("a throw inside a frame never ends the feed: the next frame is asked for all the same", async () => {
    const thrown: unknown[] = [];
    // the platform reports a frame callback's throw; this one records it, as the console would
    const raf = (callback: (frameTimeMs: number) => void): number =>
      setTimeout(() => {
        try {
          callback(Date.now());
        } catch (error) {
          thrown.push(error);
        }
      }, FRAME) as unknown as number;
    let throwOnce = true;
    const throwing: OrdersStore = {
      ...store,
      applyFrames(frames, nowMs) {
        if (throwOnce && frames.length > 0) {
          throwOnce = false;
          throw new Error("a listener threw");
        }
        store.applyFrames(frames, nowMs);
      },
    };
    feed = startOrdersFeed({
      client: ws.client,
      store: throwing,
      api: fakeApi(),
      raf,
      caf: fakeRaf.caf,
      now: () => Date.now(),
      performance: perf,
    });
    await settle(FRAME);
    ordersHandle()?.push(snap(snapshotBody())); // this frame throws
    await settle(FRAME);
    expect(thrown).toHaveLength(1);
    ordersHandle()?.push(snap(snapshotBody())); // a later snapshot still applies
    await settle(FRAME);
    expect(store.getSnapshot().status).toBe("live");
  });
});

describe("REST after each snapshot (BQ-6): never on a timer, the newest read alone", () => {
  it("one read at first paint, one after the snapshot, one after a reconnect's snapshot", async () => {
    const api = fakeApi();
    start(api);
    await settle(FRAME);
    expect(api.calls.filter((c) => c === "orders")).toHaveLength(1);
    expect(vi.mocked(api.listOrders).mock.calls[0]?.[0]).toEqual({ openOnly: true });
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(FRAME);
    expect(api.calls.filter((c) => c === "orders")).toHaveLength(2);
    await settle(60_000);
    expect(api.calls.filter((c) => c === "orders")).toHaveLength(2); // never polled
    ordersHandle()?.push(reset("reconnect"), snap(snapshotBody()));
    await settle(FRAME);
    expect(api.calls.filter((c) => c === "orders")).toHaveLength(3);
    expect(store.getSnapshot().rows.some((r) => r.id === HELD)).toBe(true);
  });

  it("a read that lands after a newer one is dropped", async () => {
    const pending: ((outcome: OrdersOutcome) => void)[] = [];
    const api = fakeApi({
      listOrders: vi.fn(() => new Promise<OrdersOutcome>((resolve) => void pending.push(resolve))),
    });
    start(api);
    await settle(FRAME);
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(FRAME);
    expect(pending).toHaveLength(2);
    const fresh = restOpen().filter((o) => o.id !== HELD);
    pending[1]?.({ kind: "ok", items: fresh, truncated: false });
    await settle(FRAME);
    pending[0]?.({ kind: "ok", items: restOpen(), truncated: false }); // the first paint, late
    await settle(FRAME);
    expect(store.getSnapshot().rows.some((r) => r.id === HELD)).toBe(false);
  });

  it("a failed read changes nothing", async () => {
    start(fakeApi({ listOrders: async () => ({ kind: "unavailable" }) }));
    await settle(FRAME);
    expect(store.getSnapshot()).toMatchObject({ source: "none", rows: [] });
  });

  it("the snapshot's read settles the held rows it carried, unless the read was truncated", async () => {
    let items = restOpen();
    let truncated = false;
    start(fakeApi({ listOrders: async () => ({ kind: "ok", items, truncated }) }));
    await settle(FRAME);
    ordersHandle()?.push(snap(snapshotBody()), d("held"));
    await settle(FRAME * 2);
    const shown = () => store.getSnapshot().rows.some((r) => r.id === COND);
    expect(shown()).toBe(true);
    // the order closed while the link was down: the reconnect's snapshot never lists a held one
    items = restOpen().filter((o) => o.id !== COND);
    truncated = true;
    const without = { orders: snapshotBody().orders.filter((o) => o.id !== COND) };
    ordersHandle()?.push(reset("reconnect"), snap(without));
    await settle(FRAME * 3);
    expect(shown()).toBe(true); // a truncated read cannot say it closed
    truncated = false;
    ordersHandle()?.push(reset("reconnect"), snap(without));
    await settle(FRAME * 3);
    expect(shown()).toBe(false);
  });
});

describe("S-02: the snapshot budget and Retry", () => {
  it("no snapshot within 5 s fails; Retry re-subscribes and a snapshot loads", async () => {
    start();
    await settle(SNAPSHOT_BUDGET_MS - FRAME);
    expect(store.getSnapshot().status).toBe("loading");
    await settle(FRAME * 2);
    expect(store.getSnapshot().status).toBe("snapshot_failed");
    expect(SNAPSHOT_BUDGET_MS).toBe(5_000);
    feed?.retry();
    await settle(FRAME);
    expect(store.getSnapshot().status).toBe("loading");
    expect(ws.handles.filter((h) => h.released)).toHaveLength(1);
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(FRAME);
    expect(store.getSnapshot().status).toBe("live");
  });

  it("a snapshot inside the budget disarms it", async () => {
    start();
    await settle(FRAME);
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(SNAPSHOT_BUDGET_MS * 2);
    expect(store.getSnapshot().status).toBe("live");
  });

  it("a directory that cannot be read fails, and Retry reads it again", async () => {
    let fail = true;
    const api = fakeApi({
      listExchangeAccounts: vi.fn(async (): Promise<AccountsOutcome> =>
        fail ? { kind: "unavailable" } : { kind: "ok", items: exchangeAccounts() },
      ),
    });
    start(api);
    await settle(FRAME);
    expect(store.getSnapshot().status).toBe("snapshot_failed");
    fail = false;
    feed?.retry();
    await settle(FRAME);
    expect(ordersHandle()).toBeDefined();
  });
});

describe("a narrowing (23 §9.5): the directory names who left (SR-E29-11)", () => {
  it("the handle keeps the old list, so the directory re-read names the account that left", async () => {
    let listed = exchangeAccounts();
    const api = fakeApi({
      listExchangeAccounts: vi.fn(async (): Promise<AccountsOutcome> => ({
        kind: "ok",
        items: listed,
      })),
    });
    start(api);
    await settle(FRAME);
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(FRAME);
    listed = listed.filter((a) => a.id !== SUB2);
    ordersHandle()?.push(reset("narrowed"));
    await settle(FRAME * 2);
    expect(api.listExchangeAccounts).toHaveBeenCalledTimes(2);
    expect(store.getSnapshot().withdrawn.map((w) => w.accountId)).toEqual([SUB2]);
    expect(ordersHandle()?.spec.opts).toEqual({ exchange_account_ids: [MAIN, SUB1] });
  });

  it("a directory that still lists every account makes nothing again", async () => {
    const api = fakeApi();
    start(api);
    await settle(FRAME);
    const before = ws.handles.length;
    ordersHandle()?.push(reset("narrowed"));
    await settle(FRAME * 2);
    expect(ws.handles.length).toBe(before);
    expect(store.getSnapshot().withdrawn).toEqual([]);
  });

  it("the link down reads offline, and no REST read is made for it", async () => {
    const api = fakeApi();
    start(api);
    await settle(FRAME);
    ws.setLink({ kind: "offline", cause: "offline" });
    await settle(FRAME);
    expect(store.getSnapshot().status).toBe("offline");
    expect(api.calls.filter((c) => c === "orders")).toHaveLength(1);
  });
});

describe("teardown", () => {
  it("stop releases the subscription, drops every cache and commits nothing more", async () => {
    start();
    await settle(FRAME);
    ordersHandle()?.push(snap(snapshotBody()));
    await settle(FRAME);
    feed?.stop();
    feed?.stop();
    expect(ws.handles.every((h) => h.released)).toBe(true);
    expect(store.getSnapshot().status).toBe("idle");
    const listener = vi.fn();
    store.subscribe(listener);
    await settle(1_000);
    expect(listener).not.toHaveBeenCalled();
    feed?.retry(); // a stopped feed does nothing
    expect(ws.handles.filter((h) => !h.released)).toEqual([]);
  });

  it("useOrdersFeed subscribes on mount and releases the subscription on unmount", async () => {
    const api = fakeApi();
    function Host(): null {
      useOrdersFeed(ws.client, store, api);
      return null;
    }
    const { unmount } = render(<Host />);
    await settle(FRAME);
    expect(ws.live("orders")).toHaveLength(1);
    unmount();
    expect(ws.live("orders")).toHaveLength(0);
    expect(store.getSnapshot().status).toBe("idle");
  });
});

function Words({ orders }: { orders: OrdersStore }) {
  const rows = useOrders(orders, (s) => s.rows);
  return (
    <ul aria-label="working orders">
      {rows.map((r) => (
        <li key={r.id}>
          {[
            r.accountLabel,
            r.symbol,
            r.sideLabel,
            r.typeLabel,
            r.qty,
            r.filledQty,
            priceLabel(r),
            triggerLabel(r),
            r.tifLabel,
            r.flagsLabel,
            r.parentLabel,
            stateLabel(r),
          ].join(" | ")}
        </li>
      ))}
    </ul>
  );
}

describe("no exchange text reaches the DOM (BQ-2, BQ-3; SR-E29-06)", () => {
  it("every row's words, through an amend rejection, a lost race and a 110001, carry no ret_msg, retCode, detail or 'already filled'", async () => {
    const tainted = (r: RestOrder): RestOrder => ({
      ...r,
      rejected_reason: "ret_msg: Order does not exist (retCode 110001), detail",
    });
    start(
      fakeApi({
        listOrders: async () => ({ kind: "ok", items: restOpen().map(tainted), truncated: false }),
      }),
    );
    render(<Words orders={store} />);
    await settle(FRAME);
    const taint = (body: ReturnType<typeof deltaBody>) => ({
      ...body,
      orders: body.orders.map((o) => ({
        ...o,
        rejected_reason: "retCode=110001 ret_msg=already filled",
      })),
    });
    ordersHandle()?.push(
      snap(snapshotBody()),
      delta(taint(deltaBody("amend_request"))),
      delta(taint(deltaBody("amend_rejected"))),
      delta(taint(deltaBody("cancel_request"))),
      delta(taint(deltaBody("cancel_110001"))),
    );
    await settle(FRAME * 2);
    const list = screen.getByRole("list", { name: "working orders" });
    expect(list.textContent).toContain("Unknown — checking");
    expect(list.textContent).not.toMatch(/ret_?msg|ret_?code|detail|already filled|110001/i);
  });
});
