/**
 * E29-S02 PR3a (#912) the amend store (`amendStore.ts`): a press's last guards (D-13 and the
 * provenance `exits.py` refuses, the arm read again at each commit, M13), judged on the orders
 * store's row (N1), one `amendOrder` per press with the token only where it is needed (P3-BQ-5),
 * the entry kept until the venue answers (P3-BQ-7), each resolution said once after it is stored
 * (RT-14, RT-06, N2), the age measured once (G-W2), the stale bound, Dismiss and prune, from the
 * goldens.
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AmendOutcome, AmendWrites } from "../../../../src/features/positions/orders/api";
import {
  AMEND_AGE_MEASURE,
  createAmendStore,
  useAmends,
  type AmendStoreOptions,
} from "../../../../src/features/positions/orders/amendStore";
import {
  AMEND_STALE_MS,
  type ArmTokenSource,
} from "../../../../src/features/positions/orders/model/amend";
import {
  mapOrder,
  type OrderConstants,
  type OrderRowModel,
  type WsOrder,
} from "../../../../src/features/positions/orders/model/orderRow";
import {
  COND,
  deltaBody,
  directory,
  ENTRY,
  ETH,
  snapshotBody,
  STOP,
  TP,
  wsItem,
  type DeltaCase,
} from "./support/orders";

const NONE: OrderConstants = { createdAtMs: null, provenance: null, tradeGroupId: null };
/** The constants a REST read gives a placed order (`rest_list_orders_open.json`). */
const PLACED: OrderConstants = { ...NONE, provenance: "placed" };

function row(id: string, wire: Record<string, unknown> = {}, constants = NONE): OrderRowModel {
  const mapped = mapOrder(
    { ...wsItem(snapshotBody(), id), ...wire } as WsOrder,
    "ws",
    directory(),
    constants,
  );
  if (mapped === null) throw new Error(`no row for ${id}`);
  return mapped;
}
const step = (name: DeltaCase, id = ETH): WsOrder => wsItem(deltaBody(name), id);

const ARMED: ArmTokenSource = { token: () => "arm-token-1" };

/** A store on a fake clock, its writes answered when the test says, its sinks recorded. */
function harness(options: Partial<AmendStoreOptions> = {}) {
  let clock = 0;
  const answers: ((outcome: AmendOutcome) => void)[] = [];
  const amendOrder = vi.fn<AmendWrites["amendOrder"]>(
    () => new Promise<AmendOutcome>((resolve) => answers.push(resolve)),
  );
  const announce = vi.fn();
  const performance = { mark: vi.fn(), measure: vi.fn(), clearMeasures: vi.fn() };
  const store = createAmendStore({
    writes: { amendOrder },
    arm: ARMED,
    announce,
    performance,
    now: () => clock,
    ...options,
  });
  return {
    store,
    amendOrder,
    announce,
    performance,
    entry: (id = ETH) => store.getSnapshot().mutations.get(id),
    /** Answers the `i`-th send and lets its promise settle. */
    answer: async (i: number, outcome: AmendOutcome): Promise<void> => {
      answers[i]?.(outcome);
      await Promise.resolve();
      await Promise.resolve();
    },
    tick: (ms: number) => {
      clock += ms;
      return clock;
    },
  };
}

describe("a press: the commit's last guards, then one amend (P3-BQ-1, P3-BQ-5)", () => {
  it("records the confirmed value and sends one PATCH with the arm token a live entry needs", () => {
    const h = harness();
    h.tick(1_000);
    const eth = row(ETH);
    expect(h.store.press(eth, "price", "2495.00")).toEqual({ kind: "sent", seq: 1 });
    expect(h.entry()).toMatchObject({
      phase: "pending",
      field: "price",
      requested: "2495.00",
      prior: "2500",
      sentAt: 1_000,
      http: "none",
    });
    expect(h.amendOrder).toHaveBeenCalledExactlyOnceWith(eth, "price", "2495.00", {
      arm: "arm-token-1",
    });
  });

  it("never sends for a native stop or a recorded take-profit (D-13, M19, M20)", () => {
    const h = harness();
    expect(h.store.press(row(STOP), "trigger_price", "63980.0")).toEqual({
      kind: "refused",
      why: "protected",
    });
    const recorded = row(TP, {}, { ...NONE, provenance: "recorded_stop" });
    expect(h.store.press(recorded, "price", "64850.0")).toMatchObject({ why: "protected" });
    expect(h.amendOrder).not.toHaveBeenCalled();
  });

  it("a read provenance other than placed is refused before any request, as exits.py refuses it (M1b)", () => {
    const h = harness();
    const adopted = row(ETH, {}, { ...NONE, provenance: "reconciliation" });
    expect(h.store.press(adopted, "price", "2495.00")).toEqual({
      kind: "refused",
      why: "not_amendable",
    });
    // a recorded stop the book no longer counts as a native stop (D01 D7's last clause)
    const recorded = row(STOP, {}, { ...NONE, provenance: "recorded_stop" });
    const uncovered = { ...recorded, protective: { kind: null, via: null } } as const;
    expect(h.store.press(uncovered, "trigger_price", "63980.0")).toMatchObject({
      why: "not_amendable",
    });
    expect(h.amendOrder).not.toHaveBeenCalled();
  });

  it("a reduce-only take-profit whose provenance no read has given is refused until one does (M1c)", () => {
    const h = harness();
    expect(h.store.press(row(TP), "price", "64850.0")).toEqual({
      kind: "refused",
      why: "provenance_unread",
    });
    expect(h.amendOrder).not.toHaveBeenCalled();
    expect(h.store.press(row(TP, {}, PLACED), "price", "64850.0").kind).toBe("sent");
  });

  it("judges the orders store's row at the commit, never the caller's stale object (N1)", () => {
    const shown = row(ETH);
    const h = harness({ current: (id) => (id === ETH ? shown : undefined) });
    expect(h.store.press({ ...shown, price: "2400" }, "price", "2495.00").kind).toBe("sent");
    expect(h.entry()).toMatchObject({ prior: "2500" });
    expect(h.amendOrder.mock.calls[0]?.[0]).toBe(shown);
  });

  it("the store's word wins: an order it shows triggered, or no longer shows, sends nothing (N1)", () => {
    const triggered = row(COND, { lifecycle_state: "triggered" });
    const h = harness({ current: (id) => (id === COND ? triggered : undefined) });
    expect(h.store.press(row(COND), "price", "64530.0")).toMatchObject({ why: "not_amendable" });
    expect(h.store.press(row(ETH), "price", "2495.00")).toMatchObject({ why: "not_amendable" });
    expect(h.amendOrder).not.toHaveBeenCalled();
  });

  it("never sends for an order that does not rest, one with an amend in flight, or a request it cannot send", () => {
    const h = harness();
    expect(
      h.store.press(row(COND, { lifecycle_state: "triggered" }), "price", "64530.0"),
    ).toMatchObject({
      why: "not_amendable",
    });
    expect(h.store.press(row(ETH), "price", "2500.00")).toMatchObject({ why: "unchanged" });
    expect(h.store.press(row(ENTRY), "qty", "0.050")).toMatchObject({ why: "not_above_filled" });
    expect(h.store.press(row(STOP, {}, NONE), "price", "1")).toMatchObject({ why: "protected" });
    expect(h.store.press(row(ETH), "price", "2495.00").kind).toBe("sent");
    expect(h.store.press(row(ETH), "price", "2490.00")).toMatchObject({ why: "in_flight" });
    expect(h.amendOrder).toHaveBeenCalledTimes(1);
  });

  it("a live risk-increasing amend without a token fails closed: nothing sent, no entry (P3-BQ-5)", () => {
    const h = harness({ arm: undefined });
    expect(h.store.press(row(ETH), "price", "2495.00")).toEqual({ kind: "refused", why: "arm" });
    expect(h.store.press(row(ENTRY), "qty", "0.200")).toMatchObject({ why: "arm" });
    expect(h.amendOrder).not.toHaveBeenCalled();
    expect(h.store.getSnapshot().mutations.size).toBe(0);
  });

  it("the commit reads the arm again: a token gone since the gate read sends nothing (M13)", () => {
    let token: string | null = "arm-token-1";
    const h = harness({ arm: { token: () => token } });
    token = null;
    expect(h.store.press(row(ETH), "price", "2495.00")).toMatchObject({ why: "arm" });
    expect(h.amendOrder).not.toHaveBeenCalled();
  });

  it.each([
    ["armed, then not", ["arm-token-1", null], [{ kind: "sent" }, { why: "arm" }], ["arm-token-1"]],
    ["not, then armed", [null, "arm-token-2"], [{ why: "arm" }, { kind: "sent" }], ["arm-token-2"]],
  ] as const)(
    "two presses on one account across a token change, %s: each commit reads its own (M13-memo)",
    (_, tokens, results, sentWith) => {
      let token: string | null = tokens[0];
      const h = harness({ arm: { token: () => token } });
      // COND's price and ENTRY's quantity raised: both risk-increasing, both on LIVE Sub-1
      expect(h.store.press(row(COND), "price", "64530.0")).toMatchObject(results[0]);
      token = tokens[1];
      expect(h.store.press(row(ENTRY), "qty", "0.200")).toMatchObject(results[1]);
      expect(h.amendOrder.mock.calls.map((call) => call[3]?.arm)).toEqual(sentWith);
    },
  );

  it("a cut and a take-profit's price go without the token, whatever the session holds (M7, M8, M11)", () => {
    const h = harness();
    h.store.press(row(ENTRY), "qty", "0.100");
    h.store.press(row(TP, {}, PLACED), "price", "64850.0");
    expect(h.amendOrder.mock.calls.map((call) => call[3])).toEqual([{ arm: null }, { arm: null }]);
  });

  it("a demo entry's price goes without the arm (M10)", () => {
    const h = harness({ arm: undefined });
    expect(h.store.press(row(ETH, { environment: "demo" }), "price", "2495.00").kind).toBe("sent");
    expect(h.amendOrder.mock.calls[0]?.[3]).toEqual({ arm: null });
  });
});

describe("resolved on the venue's word, each resolution said once", () => {
  it("Optimistic amend is clearly pending: confirmed only by the amend step, said politely once (RT-14)", async () => {
    const h = harness();
    h.store.press(row(ETH), "price", "2495.00");
    h.store.observe(step("amend_request"), "delta");
    await h.answer(0, { kind: "accepted", lifecycle: "submitted" });
    expect(h.entry()).toMatchObject({ phase: "pending", sawPending: true, http: "accepted" });
    expect(h.announce).not.toHaveBeenCalled();
    h.tick(1_200);
    h.store.observe(step("amend_accepted"), "delta");
    expect(h.entry()).toBeUndefined();
    expect(h.announce.mock.calls).toEqual([["polite", "Amend confirmed: price 2,495."]]);
    expect(h.performance.measure.mock.calls).toEqual([
      [AMEND_AGE_MEASURE, { start: 0, end: 1_200, detail: { outcome: "confirmed" } }],
    ]);
  });

  it("Amend rejection leaves the order untouched: said assertively once, though the 502 and the frame both say it (M25)", async () => {
    const h = harness();
    h.store.press(row(ETH), "price", "2495.00");
    h.store.observe(step("amend_request"), "delta");
    await h.answer(0, { kind: "exchange_refused" });
    h.store.observe(step("amend_rejected"), "delta");
    expect(h.entry()).toMatchObject({ phase: "rejected", said: "rejected", prior: "2500" });
    expect(h.announce.mock.calls).toEqual([
      ["assertive", "Amend rejected. Your order is unchanged: the price is still 2,500."],
    ]);
    expect(h.performance.measure).toHaveBeenCalledTimes(1);
  });

  it("an answer settles its own press alone", async () => {
    const h = harness();
    expect(h.store.press(row(ETH), "price", "2495.00")).toMatchObject({ seq: 1 });
    h.store.observe(step("amend_request"), "delta");
    h.store.observe(step("amend_accepted"), "delta");
    expect(h.store.press(row(ETH), "price", "2490.00")).toMatchObject({ seq: 2 });
    await h.answer(0, { kind: "unavailable" });
    expect(h.entry()).toMatchObject({ seq: 2, phase: "pending", http: "none" });
    await h.answer(1, { kind: "arm_refused" });
    expect(h.entry()).toMatchObject({ seq: 2, phase: "not_sent", refusal: "arm_refused" });
  });

  it("a write that throws settles as no answer: Unconfirmed", async () => {
    const h = harness({
      writes: { amendOrder: () => Promise.reject(new Error("boom")) },
    });
    h.store.press(row(ETH), "price", "2495.00");
    await Promise.resolve();
    await Promise.resolve();
    expect(h.entry()?.phase).toBe("unconfirmed");
  });

  it("the stale bound reads Unconfirmed, never confirmed, measured once (M6)", () => {
    const h = harness();
    h.store.press(row(ETH), "price", "2495.00");
    h.store.expire(h.tick(AMEND_STALE_MS - 1));
    expect(h.entry()?.phase).toBe("pending");
    h.store.expire(h.tick(1));
    expect(h.entry()?.phase).toBe("unconfirmed");
    h.store.expire(h.tick(AMEND_STALE_MS));
    expect(h.performance.measure.mock.calls).toEqual([
      [AMEND_AGE_MEASURE, { start: 0, end: AMEND_STALE_MS, detail: { outcome: "unconfirmed" } }],
    ]);
    expect(h.announce).not.toHaveBeenCalled();
  });
});

describe("Dismiss, a new press, prune and the sinks", () => {
  it("Dismiss clears a rejected line, never a pending or an unconfirmed one", async () => {
    const h = harness();
    h.store.press(row(ETH), "price", "2495.00");
    h.store.dismiss(ETH);
    expect(h.entry()?.phase).toBe("pending");
    await h.answer(0, { kind: "exchange_refused" });
    h.store.dismiss(ETH);
    expect(h.entry()).toBeUndefined();
  });

  it("a new press clears an undismissed rejected line silently", async () => {
    const h = harness();
    h.store.press(row(ETH), "price", "2495.00");
    await h.answer(0, { kind: "exchange_refused" });
    expect(h.store.press(row(ETH), "price", "2490.00")).toMatchObject({ kind: "sent", seq: 2 });
    expect(h.entry()).toMatchObject({ phase: "pending", requested: "2490.00", said: null });
    expect(h.announce).toHaveBeenCalledTimes(1);
  });

  it("prune drops the entry of an order the live view no longer shows, unsaid", () => {
    const h = harness();
    h.store.press(row(ETH), "price", "2495.00");
    h.store.prune(new Set([ETH]));
    expect(h.entry()).toBeDefined();
    h.store.prune(new Set([TP]));
    expect(h.entry()).toBeUndefined();
    expect(h.announce).not.toHaveBeenCalled();
    expect(h.performance.measure.mock.calls[0]?.[1]).toMatchObject({
      detail: { outcome: "dropped" },
    });
  });

  it("an item for an order with no amend, or one naming none, publishes nothing", () => {
    const h = harness();
    const listener = vi.fn();
    h.store.subscribe(listener);
    h.store.observe(step("cancel_lost_race", TP), "delta");
    h.store.observe({ orders: [] }, "delta");
    expect(listener).not.toHaveBeenCalled();
    expect(h.store.getSnapshot().version).toBe(0);
  });

  it("an announcer that throws costs no step: stored and published first, its error reported (N2)", () => {
    const boom = new Error("region gone");
    const report = vi.fn();
    const h = harness({
      announce: () => {
        throw boom;
      },
      report,
    });
    h.store.press(row(ETH), "price", "2495.00");
    h.store.observe(step("amend_request"), "delta");
    const listener = vi.fn();
    h.store.subscribe(listener);
    h.store.observe(step("amend_rejected"), "delta");
    expect(h.entry()).toMatchObject({ phase: "rejected", said: "rejected" });
    expect(listener).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenCalledExactlyOnceWith(boom);
  });

  it("a measure that throws never harms the amend; past the cap the measures are cleared", () => {
    const h = harness();
    h.performance.measure.mockImplementation(() => {
      throw new Error("no timeline");
    });
    h.store.press(row(ETH), "price", "2495.00");
    h.store.observe(step("amend_request"), "delta");
    h.store.observe(step("amend_accepted"), "delta");
    expect(h.entry()).toBeUndefined();
    const capped = harness();
    for (let i = 0; i < 1_000; i += 1) {
      capped.store.press(row(ETH), "price", "2495.00");
      capped.store.prune(new Set());
    }
    expect(capped.performance.clearMeasures).toHaveBeenCalledExactlyOnceWith(AMEND_AGE_MEASURE);
  });

  it("useAmends re-renders the selection on a change and lets go on unmount", () => {
    const h = harness();
    const { result, unmount } = renderHook(() =>
      useAmends(h.store, (s) => s.mutations.get(ETH)?.phase ?? null),
    );
    expect(result.current).toBeNull();
    act(() => {
      h.store.press(row(ETH), "price", "2495.00");
    });
    expect(result.current).toBe("pending");
    unmount();
  });
});
