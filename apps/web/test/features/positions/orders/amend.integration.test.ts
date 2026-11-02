/**
 * E29-S02 PR3a (#912) the amend engine end to end, without a screen: the real feed
 * (`startOrdersFeed`), orders store, amend store and writes (`createOrdersWrites`) behind a fake
 * `fetch` and a fake topic handle, fed the goldens' steps (`ws_orders_deltas.json`). The ticket's
 * integration plan: amend-ack, amend-reject, the unknown amend reconciled, an untracked adoption, a
 * missed accept frame, and the stale bound (P3-BQ-7: confirmed or rejected only on the venue's word).
 *
 * Two frames are goldens re-stamped as PR2's tests re-stamp them: the accepted ETH step read again by
 * reconciliation (`change: "reconcile"`) and by a snapshot (no `change` key, as `ws_topics.py`
 * builds one).
 */
import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { AccountsOutcome } from "../../../../src/features/positions/api";
import {
  createOrdersWrites,
  type OrdersApi,
  type OrdersOutcome,
} from "../../../../src/features/positions/orders/api";
import {
  createAmendStore,
  type AmendStore,
} from "../../../../src/features/positions/orders/amendStore";
import {
  AMEND_STALE_MS,
  NO_ARM,
  type ArmTokenSource,
} from "../../../../src/features/positions/orders/model/amend";
import { editGate } from "../../../../src/features/positions/orders/model/gates";
import type { WsOrder } from "../../../../src/features/positions/orders/model/orderRow";
import {
  createOrdersStore,
  type OrdersStore,
} from "../../../../src/features/positions/orders/ordersStore";
import {
  startOrdersFeed,
  type OrdersFeed,
} from "../../../../src/features/positions/orders/wsOrders";
import {
  ADOPTED,
  COND,
  delta,
  deltaBody,
  ENTRY,
  ETH,
  exchangeAccounts,
  fakeClient,
  fakeRaf,
  golden,
  reset,
  restOpen,
  snap,
  snapshotBody,
  TP,
  wsItem,
  type DeltaCase,
  type FakeClient,
} from "./support/orders";

const FRAME = 16;
const ARMED: ArmTokenSource = { token: () => "arm-token-1" };

interface Patch {
  readonly path: string;
  readonly key: string | null;
  readonly arm: string | null;
  readonly body: unknown;
}

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let ws: FakeClient;
let feed: OrdersFeed | undefined;
let store: OrdersStore;
let amends: AmendStore;
let patches: Patch[];
let replies: ((res: Response) => void)[];
let announce: Mock<(politeness: "polite" | "assertive", text: string) => void>;

const settle = async (ms = 0): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};
const push = async (
  ...frames: Parameters<FakeClient["handles"][number]["push"]>
): Promise<void> => {
  ws.live("orders")[0]?.push(...frames);
  await settle(FRAME);
};
const step = (name: DeltaCase) => delta(deltaBody(name));
const rowOf = (id: string) => store.getSnapshot().rows.find((r) => r.id === id);
const entry = (id = ETH) => amends.getSnapshot().mutations.get(id);
/** Answers the `i`-th PATCH. */
async function reply(i: number, res: Response): Promise<void> {
  replies[i]?.(res);
  await settle();
}
/** Presses the order's amend as it stands in the store. */
function press(id: string, field: "price" | "trigger_price" | "qty", requested: string) {
  const row = rowOf(id);
  if (row === undefined) throw new Error(`no row for ${id}`);
  return amends.press(row, field, requested);
}
/**
 * The golden's accepted ETH step as a later read gives it: a reconcile step, or a snapshot's item,
 * which carries no `change` key at all (`ws_topics.py` omits it).
 */
function reread(change: "reconcile" | null): WsOrder {
  const item = { ...wsItem(deltaBody("amend_accepted"), ETH) };
  item.updated_at_ms += 4_000;
  if (change === null) delete item.change;
  else item.change = change;
  return item;
}

/** The live view: the feed, its stores, the snapshot; the session's arm is `arm`. */
async function open(arm: ArmTokenSource = ARMED): Promise<void> {
  patches = [];
  replies = [];
  announce = vi.fn();
  const fetch = vi.fn((path: string, init: RequestInit): Promise<Response> => {
    const headers = new Headers(init.headers);
    patches.push({
      path,
      key: headers.get("Idempotency-Key"),
      arm: headers.get("X-Arm-Token"),
      body: typeof init.body === "string" ? JSON.parse(init.body) : null,
    });
    return new Promise((resolve) => replies.push(resolve));
  });
  amends = createAmendStore({
    writes: createOrdersWrites({ fetch, sleep: async () => undefined }),
    arm,
    announce,
    now: () => Date.now(),
    performance: null,
  });
  store = createOrdersStore({ onItem: (item, via) => amends.observe(item, via) });
  const api: OrdersApi = {
    listOrders: async (): Promise<OrdersOutcome> => ({
      kind: "ok",
      items: restOpen(),
      truncated: false,
    }),
    listExchangeAccounts: async (): Promise<AccountsOutcome> => ({
      kind: "ok",
      items: exchangeAccounts(),
    }),
  };
  feed = startOrdersFeed({
    client: ws.client,
    store,
    amends,
    api,
    ...fakeRaf,
    now: () => Date.now(),
    performance: null,
  });
  await settle();
  await push(snap(snapshotBody()));
}

beforeEach(() => {
  vi.useFakeTimers();
  ws = fakeClient();
});
afterEach(() => {
  feed?.stop();
  feed = undefined;
  vi.useRealTimers();
});

describe("Optimistic amend is clearly pending (amend-ack)", () => {
  it("an armed LIVE entry: Amending on the old terms until the amend step confirms it", async () => {
    await open();
    expect(press(ETH, "price", "2495.00")).toEqual({ kind: "sent", seq: 1 });
    expect(patches).toEqual([
      {
        path: `/api/v1/orders/${ETH}`,
        key: expect.any(String) as string,
        arm: "arm-token-1",
        body: golden("rest_amend_order_request.json"),
      },
    ]);
    await push(step("amend_request"));
    expect(rowOf(ETH)).toMatchObject({ price: "2500", state: { word: "Amending" } });
    expect(entry()).toMatchObject({ phase: "pending", sawPending: true });
    await reply(0, json(202, { id: ETH, lifecycle_state: "submitted" }));
    expect(entry()?.phase).toBe("pending");
    await push(step("amend_accepted"));
    expect(rowOf(ETH)).toMatchObject({ price: "2495", state: { word: "Working" } });
    expect(entry()).toBeUndefined();
    expect(announce.mock.calls).toEqual([["polite", "Amend confirmed: price 2,495."]]);
  });

  it("the stale bound reads Unconfirmed; the venue's late amend step still confirms it", async () => {
    await open();
    press(ETH, "price", "2495.00");
    await push(step("amend_request"));
    await reply(0, json(202, { id: ETH, lifecycle_state: "amend_pending" }));
    await settle(AMEND_STALE_MS + 2 * FRAME);
    expect(entry()?.phase).toBe("unconfirmed");
    expect(announce).not.toHaveBeenCalled();
    await push(step("amend_accepted"));
    expect(entry()).toBeUndefined();
    expect(announce.mock.calls).toEqual([["polite", "Amend confirmed: price 2,495."]]);
  });

  it("a missed accept frame: after a reset, the snapshot read after the 202 confirms it", async () => {
    await open();
    press(ETH, "price", "2495.00");
    await push(step("amend_request"));
    await push(reset("reconnect"));
    await reply(0, json(202, { id: ETH, lifecycle_state: "submitted" }));
    expect(entry()?.phase).toBe("pending");
    const orders = snapshotBody().orders.map((o) => (o.id === ETH ? reread(null) : o));
    await push(snap({ orders }));
    expect(rowOf(ETH)?.price).toBe("2495");
    expect(entry()).toBeUndefined();
    expect(announce.mock.calls).toEqual([["polite", "Amend confirmed: price 2,495."]]);
  });
});

describe("Amend rejection leaves the order untouched (amend-reject)", () => {
  it("the 502 and the venue's step both reject it: Working at 2,500, said once, no exchange text", async () => {
    await open();
    press(ETH, "price", "2495.00");
    await push(step("amend_request"));
    await reply(
      0,
      json(502, {
        type: "https://candleviewer.local/errors/exchange_error",
        title: "x",
        status: 502,
        code: "exchange_error",
        detail: "EXCHANGE-TEXT",
        exchange: { ret_code: 110007 },
      }),
    );
    expect(entry()?.phase).toBe("rejected");
    await push(step("amend_rejected"));
    expect(rowOf(ETH)).toMatchObject({ price: "2500", state: { word: "Working" } });
    expect(entry()).toMatchObject({ phase: "rejected", prior: "2500" });
    expect(announce.mock.calls).toEqual([
      ["assertive", "Amend rejected. Your order is unchanged: the price is still 2,500."],
    ]);
    expect(JSON.stringify(announce.mock.calls)).not.toMatch(/110007|EXCHANGE-TEXT/);
    amends.dismiss(ETH);
    expect(entry()).toBeUndefined();
  });

  it("a LIVE entry's price without the arm sends nothing; a cut goes, armless (P3-BQ-5)", async () => {
    await open(NO_ARM);
    expect(press(ETH, "price", "2495.00")).toEqual({ kind: "refused", why: "arm" });
    expect(press(ENTRY, "qty", "0.100")).toMatchObject({ kind: "sent" });
    expect(patches.map((p) => [p.path, p.arm, p.body])).toEqual([
      [`/api/v1/orders/${ENTRY}`, null, { qty: "0.100" }],
    ]);
  });
});

describe("the unknown amend, reconciled (D01 D4 × Unknown)", () => {
  it("amend_unknown reads Unknown — checking; reconciliation finding 2,495 confirms it (D01:228)", async () => {
    await open();
    press(ETH, "price", "2495.00");
    await push(step("amend_request"));
    await reply(0, json(202, { id: ETH, lifecycle_state: "unknown" }));
    expect(entry()?.phase).toBe("unconfirmed");
    await push(step("amend_unknown"));
    expect(rowOf(ETH)?.state.word).toBe("Unknown — checking");
    expect(entry()?.phase).toBe("unconfirmed");
    await push(delta({ orders: [reread("reconcile")] }));
    expect(entry()).toBeUndefined();
    expect(announce.mock.calls).toEqual([["polite", "Amend confirmed by reconciliation."]]);
  });

  it("an armless LIVE take-profit gone unknown, then filled meanwhile: the overlay ends with it", async () => {
    await open(NO_ARM);
    expect(press(TP, "price", "64850.0")).toMatchObject({ kind: "sent" });
    expect(patches[0]?.arm).toBeNull();
    await reply(0, json(202, { id: TP, lifecycle_state: "unknown" }));
    expect(entry(TP)?.phase).toBe("unconfirmed");
    await push(step("cancel_110001"));
    expect(entry(TP)?.phase).toBe("unconfirmed");
    await push(step("reconcile_filled"));
    expect(rowOf(TP)?.state.word).toBe("Filled");
    expect(entry(TP)).toBeUndefined();
    expect(announce).not.toHaveBeenCalled();
  });
});

describe("untracked adoption and a hold (S9, INV-B1-n)", () => {
  it("an order adopted as untracked is shown, never amended", async () => {
    await open();
    await push(step("untracked_adopted"));
    const adopted = rowOf(ADOPTED);
    expect(adopted?.state.lifecycle).toBe("untracked");
    expect(press(ADOPTED, "price", "60010")).toEqual({ kind: "refused", why: "not_amendable" });
    expect(patches).toEqual([]);
    const gate = editGate(adopted as NonNullable<typeof adopted>, "price", {
      viewAs: null,
      permissions: ["orders:write"],
      readOnlyAccounts: new Set(),
      restReachable: true,
      cancelling: new Set(),
      amends: new Map(),
      hasSteps: () => true,
      arm: ARMED,
      armKey: "Ctrl+Shift+T",
      role: "owner",
    });
    expect(gate).toMatchObject({ kind: "gated", leg: "untracked" });
  });

  it("an amend pending on an order put on hold ends with nothing said", async () => {
    await open();
    expect(press(COND, "price", "64530.0")).toMatchObject({ kind: "sent" });
    await push(step("held"));
    expect(rowOf(COND)?.state.lifecycle).toBe("held");
    expect(entry(COND)).toBeUndefined();
    expect(announce).not.toHaveBeenCalled();
  });
});
